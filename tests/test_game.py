import os
import random
import tempfile
import unittest
from collections import deque

from game import engine, world
from game.engine import Game
from game.items import ITEMS, SHOP


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def new_game(**kwargs):
    clock = Clock()
    return Game(":memory:", clock=clock, **kwargs), clock


def make_hero(game, uid, name="Герой", stats=("str",) * 10):
    game.stage(uid)
    game.set_name(uid, name)
    for key in stats:
        game.change_stat(uid, key, 1)
    assert game.finish_creation(uid) is not None
    return game.players[uid]


class WorldTest(unittest.TestCase):
    def test_map_is_square_and_known(self):
        self.assertEqual(len(world.MAP_ROWS), 2 * world.RADIUS + 1)
        for row in world.MAP_ROWS:
            self.assertEqual(len(row), 2 * world.RADIUS + 1)
            self.assertTrue(set(row) <= set(world.TILES))
        self.assertTrue(world.tile_at(world.CAMP).safe)

    def test_every_walkable_tile_reachable_from_camp(self):
        seen, queue = {world.CAMP}, deque([world.CAMP])
        while queue:
            x, y = queue.popleft()
            for nxt in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nxt not in seen and world.in_bounds(nxt) and world.tile_at(nxt).passable:
                    seen.add(nxt)
                    queue.append(nxt)
        walkable = {pos for pos, tile in world.iter_tiles() if tile.passable}
        self.assertEqual(walkable, seen)

    def test_content_references_are_valid(self):
        for pos in list(world.CHESTS) + list(world.BOSSES):
            self.assertTrue(world.tile_at(pos).passable, pos)
        for tile in world.TILES.values():
            for kind in tile.spawns:
                self.assertIn(kind, world.MOBS)
        for mob in world.MOBS.values():
            for item_id, _ in mob.loot:
                self.assertIn(item_id, ITEMS)
        for tier in world.CHEST_TIERS.values():
            for item_id in tier.pool:
                self.assertIn(item_id, ITEMS)
        for _, item_id, _, _ in world.GATHERING.values():
            self.assertIn(item_id, ITEMS)
        for item_id in SHOP:
            self.assertTrue(ITEMS[item_id].value > 0)
        self.assertEqual(len(world.CHESTS), 8)


class CreationTest(unittest.TestCase):
    def test_creation_flow(self):
        game, _ = new_game()
        self.assertEqual(game.stage(1), "name")
        self.assertIn("⚠️", game.set_name(1, "x").text)
        game.set_name(1, "Арагорн")
        self.assertEqual(game.stage(1), "stats")
        self.assertIsNone(game.finish_creation(1))  # очки не распределены
        for _ in range(10):
            game.change_stat(1, "dex", 1)
        game.change_stat(1, "dex", -1)
        game.change_stat(1, "luck", 1)
        self.assertIsNotNone(game.finish_creation(1))
        p = game.players[1]
        self.assertEqual((p.stage, p.stats["dex"], p.stats["luck"], p.points), ("play", 10, 2, 0))
        self.assertEqual(p.hp, p.max_hp)

    def test_names_are_unique_case_insensitive(self):
        game, _ = new_game()
        make_hero(game, 1, "Гэндальф")
        game.stage(2)
        self.assertIn("занято", game.set_name(2, "гэндальф").text)

    def test_invite_codes(self):
        game, _ = new_game(invite_only=True, admins={99})
        self.assertEqual(game.stage(1), "invite")
        self.assertEqual(game.stage(99), "name")
        self.assertIn("Неверный", game.redeem(1, "nope").text)
        code = game.new_invite()
        game.redeem(1, code.lower())
        self.assertEqual(game.stage(1), "name")
        self.assertEqual(game.db.execute("SELECT COUNT(*) FROM invite_codes").fetchone()[0], 0)

    def test_progress_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "game.db")
            game = Game(path)
            p = make_hero(game, 1, "Боромир")
            p.gold = 123
            game.equip(1, "potion")  # нельзя надеть — ничего не меняется
            game.give(1, "short_sword")
            game.equip(1, "short_sword")
            game.move(1, 1, 0)
            game.db.close()

            restored = Game(path)
            q = restored._get(1)
            self.assertEqual((q.name, q.gold, q.weapon, q.pos, q.stage),
                             ("Боромир", 123, "short_sword", (1, 0), "play"))
            self.assertIn((2, 0), q.seen)
            restored.db.close()


class PlayTest(unittest.TestCase):
    def setUp(self):
        random.seed(1)
        self.game, self.clock = new_game()
        self.p = make_hero(self.game, 1)

    def teleport(self, pos):
        self.p.x, self.p.y = pos
        self.p.fighting = 0

    def clear(self, pos):
        for mob in self.game.mobs_at(pos):
            del self.game.mobs[mob.id]
        self.game.respawn_at[pos] = self.clock.now + 10_000
        self.game.boss_respawn_at[pos] = self.clock.now + 10_000

    def test_river_blocks_and_bridge_lets_through(self):
        self.teleport((2, 0))
        self.assertIn("мост", self.game.move(1, 1, 0).text)
        self.assertEqual(self.p.pos, (2, 0))
        self.teleport((2, 2))
        self.clear((3, 2))
        self.game.move(1, 1, 0)
        self.assertEqual(self.p.pos, (3, 2))

    def test_edge_of_world(self):
        self.teleport((0, 5))
        self.assertIn("край мира", self.game.move(1, 0, 1).text)

    def test_kill_mob_gives_rewards_and_respawns(self):
        pos = (1, 1)
        self.clear(pos)
        mob = self.game._spawn(pos, "rabbit")
        self.teleport(pos)
        self.p.stats["str"] = 50
        reply = self.game.attack(1, mob.id)
        self.assertIn("повержен", reply.text)
        self.assertNotIn(mob.id, self.game.mobs)
        self.assertEqual(self.p.kills, 1)
        self.clock.now += engine.MOB_RESPAWN + 20_000
        self.game.look(1)
        self.assertTrue(self.game.mobs_at(pos))

    def test_group_fight_shares_xp_and_notifies(self):
        ally = make_hero(self.game, 2, "Союзник")
        pos = (1, 1)
        self.clear(pos)
        mob = self.game._spawn(pos, "bear")
        self.teleport(pos)
        ally.x, ally.y = pos
        self.game.attack(2, mob.id)
        ally.hp = ally.max_hp
        mob.hp = 1
        reply = self.game.attack(1, mob.id)
        self.assertTrue(ally.xp > 0 or ally.level > 1)
        self.assertTrue(any(uid == 2 and "за помощь" in text for uid, text in reply.notify))

    def test_death_sends_to_camp(self):
        pos = (5, 3)
        self.teleport(pos)
        self.p.gold = 100
        self.p.hp = 1
        self.p.stats["dex"] = 0  # без уворотов
        boss = next(m for m in self.game.mobs_at(pos) if m.boss)
        boss.hp = 10_000
        reply = self.game.attack(1, boss.id)
        self.assertIn("погиб", reply.text)
        self.assertEqual((self.p.pos, self.p.gold), (world.CAMP, 90))
        self.assertEqual(self.p.fighting, 0)

    def test_chest_guarded_then_opened_once(self):
        pos = (-1, -2)
        self.teleport(pos)
        self.game._spawn(pos, "frog")
        self.assertIn("охраняют", self.game.open_chest(1).text)
        self.clear(pos)
        gold = self.p.gold
        self.assertIn("открываешь", self.game.open_chest(1).text)
        self.assertGreater(self.p.gold, gold)
        self.assertIn("пуст", self.game.open_chest(1).text)
        self.clock.now += engine.CHEST_RESPAWN + 1
        self.assertIn("стоит сундук", self.game.look(1).text)

    def test_shop_equipment_and_selling(self):
        self.teleport(world.CAMP)
        self.p.gold = 1000
        self.game.buy(1, "short_sword")
        self.game.buy(1, "chainmail")
        self.game.equip(1, "short_sword")
        self.game.equip(1, "chainmail")
        self.assertEqual((self.p.weapon, self.p.armor), ("short_sword", "chainmail"))
        self.assertEqual(self.p.defense, 4)
        self.game.give(1, "rusty_shiv")
        self.game.equip(1, "rusty_shiv")
        self.assertEqual(self.p.bag.get("short_sword"), 1)  # старое оружие вернулось в рюкзак
        gold = self.p.gold
        self.game.sell(1, "short_sword")
        self.assertEqual(self.p.gold, gold + ITEMS["short_sword"].sell_price)
        self.game.unequip(1, "armor")
        self.assertEqual((self.p.armor, self.p.bag.get("chainmail")), ("", 1))

    def test_selling_only_in_camp(self):
        self.teleport((1, 0))
        self.game.give(1, "wolf_pelt")
        self.assertIn("только торговцу", self.game.sell(1, "wolf_pelt").text)

    def test_ring_bonus_and_books(self):
        self.game.give(1, "ring_str")
        base_hp = self.p.max_hp
        self.game.equip(1, "ring_str")
        self.assertEqual(self.p.max_hp, base_hp + 6)
        self.game.give(1, "old_book")
        self.game.use(1, "old_book", "bag")
        self.assertEqual(self.p.stats["int"], 2)

    def test_potion_heals(self):
        self.p.hp = 5
        self.game.use(1, "potion", "look")
        self.assertGreater(self.p.hp, 5)
        self.assertEqual(self.p.bag["potion"], 1)

    def test_level_up_gives_points_to_spend(self):
        self.game._gain_xp(self.p, 1000)
        self.assertGreater(self.p.level, 1)
        points = self.p.points
        self.assertGreater(points, 0)
        self.game.change_stat(1, "luck", 1)
        self.game.change_stat(1, "luck", -1)  # после создания очки не возвращаются
        self.assertEqual((self.p.points, self.p.stats["luck"]), (points - 1, 2))

    def test_regen_over_time(self):
        self.p.hp = 1
        self.p.regen_at = self.clock.now
        self.clock.now += engine.REGEN_EVERY * 5
        self.game.look(1)
        self.assertEqual(self.p.hp, 6)

    def test_bag_limit(self):
        self.p.bag = {"stone": engine.BAG_SIZE}
        self.assertIn("полон", self.game._give(self.p, "potion"))

    def test_gathering_cooldown(self):
        pos = (-1, -2)
        self.teleport(pos)
        self.clear(pos)
        self.game.gather(1)
        self.assertIn("устал", self.game.gather(1).text)

    def test_chat_reaches_players_in_same_location(self):
        make_hero(self.game, 2, "Сосед")
        reply = self.game.say(1, "привет")
        self.assertEqual(reply.notify, [(2, "💬 Герой: привет")])
        self.teleport((1, 0))
        self.assertEqual(self.game.say(1, "эй").notify, [])

    def test_all_screens_render(self):
        for pos, tile in world.iter_tiles():
            if tile.passable:
                self.teleport(pos)
                self.game.look(1)
        self.game.give(1, "potion")
        for screen in (self.game.hero, self.game.bag, self.game.gear, self.game.world_map, self.game.stats):
            self.assertTrue(screen(1).text)
        self.teleport(world.CAMP)
        self.assertIn("Торговец", self.game.shop(1).text)
        for item_id in ITEMS:
            self.game.give(1, item_id)
            self.assertTrue(self.game.item(1, item_id).text)
        self.assertIn("Герой", self.game.top().text)

    def test_callback_data_fits_telegram_limit(self):
        self.teleport(world.CAMP)
        self.p.gold = 10_000
        for item_id in ITEMS:
            self.game.give(1, item_id)
        replies = [self.game.shop(1), self.game.bag(1), self.game.gear(1), self.game.look(1)]
        replies += [self.game.item(1, i) for i in ITEMS]
        for reply in replies:
            for row in reply.buttons:
                for _, data in row:
                    self.assertLessEqual(len(data.encode()), 64)


if __name__ == "__main__":
    unittest.main()
