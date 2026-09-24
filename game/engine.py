"""Игровая логика: герои, общий мир, бои, сундуки, рюкзак, торговец.

Не зависит от Telegram: каждый публичный метод возвращает Reply — текст,
кнопки и уведомления для других игроков. Отправкой занимается bot.py.
"""
import itertools
import json
import math
import random
import re
import secrets
import sqlite3
import string
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from functools import wraps

from game import world
from game.items import EQUIP_SLOTS, FISTS, ITEMS, PERKS, SHOP, STAT_NAMES

MOB_RESPAWN = 90        # сек. между появлениями обычных монстров в локации
BOSS_RESPAWN = 600      # босс возвращается через 10 минут
CHEST_RESPAWN = 900     # сундук наполняется заново через 15 минут
ACTIVE_WINDOW = 600     # игрок «в сети», если что-то делал за последние 10 минут
REGEN_EVERY = 20        # +1 ❤️ каждые 20 секунд
AMBUSH_CHANCE = 0.35    # шанс, что агрессивный монстр нападёт первым
DEATH_GOLD_LOSS = 0.1
BAG_SIZE = 30
START_POINTS = 10
POINTS_PER_LEVEL = 2
STATS = ("str", "dex", "luck", "int")
NAME_RE = re.compile(r"[\w \-]{2,16}")

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS players ("
    "id INTEGER PRIMARY KEY, name TEXT, level INTEGER, xp INTEGER, kills INTEGER, data TEXT)",
    "CREATE TABLE IF NOT EXISTS invite_codes (code TEXT PRIMARY KEY)",
)

INTRO = (
    "Ты стоишь у костра в лагере — единственном безопасном месте в этих землях.\n"
    "На севере — старые шахты гоблинов, на западе — разрушенная башня, "
    "за рекой на востоке хозяйничают орки, а на юго-востоке — бандиты.\n"
    "Ищи сундуки, побеждай врагов, объединяйся с другими героями против боссов!"
)


@dataclass
class Player:
    id: int
    name: str = ""
    stage: str = "name"  # invite -> name -> stats -> play
    x: int = 0
    y: int = 0
    level: int = 1
    xp: int = 0
    hp: int = 0
    gold: int = 20
    stats: dict = field(default_factory=lambda: dict.fromkeys(STATS, 1))
    points: int = START_POINTS
    weapon: str = ""
    armor: str = ""
    ring: str = ""
    amulet: str = ""
    bag: dict = field(default_factory=lambda: {"potion": 2, "garlic": 2})
    kills: int = 0
    seen: set = field(default_factory=set)  # открытые клетки карты
    regen_at: float = 0.0
    # дальше — только в памяти, в базу не сохраняется
    last_seen: float = 0.0
    fighting: int = 0            # id монстра, с которым идёт бой
    came_from: tuple = world.CAMP
    gather_at: float = 0.0

    def stat(self, key):
        bonus = sum(it.stat[1] for it in (ITEMS.get(self.ring), ITEMS.get(self.amulet))
                    if it and it.stat[0] == key)
        return self.stats[key] + bonus

    @property
    def pos(self):
        return (self.x, self.y)

    @property
    def weapon_item(self):
        return ITEMS.get(self.weapon, FISTS)

    @property
    def max_hp(self):
        return 20 + 5 * self.level + 3 * self.stat("str")

    @property
    def base_damage(self):
        w = self.weapon_item
        return w.dmg + sum(self.stat(s) for s in w.scale) / 2 + self.level

    @property
    def defense(self):
        armor = ITEMS.get(self.armor)
        return (armor.defense if armor else 0) + self.level // 3

    @property
    def crit_chance(self):
        return min(40, 5 + 2 * self.stat("luck")) / 100

    @property
    def perk_chance(self):
        return min(40, 10 + self.stat("luck")) / 100

    @property
    def dodge_chance(self):
        return min(35, 2 * self.stat("dex")) / 100

    @property
    def flee_chance(self):
        return min(90, 40 + 3 * self.stat("dex")) / 100

    @property
    def xp_needed(self):
        return int(50 * 1.3 ** (self.level - 1))

    @property
    def bag_count(self):
        return sum(self.bag.values())


TRANSIENT = {"last_seen", "fighting", "came_from", "gather_at"}


@dataclass
class Mob:
    id: int
    kind: str
    pos: tuple
    hp: int
    boss: bool = False
    damage_by: dict = field(default_factory=dict)  # id игрока -> нанесённый урон

    @property
    def type(self):
        return world.MOBS[self.kind]

    @property
    def label(self):
        return f"{self.type.emoji} {self.type.name}" + (" (босс)" if self.boss else "")


@dataclass
class Reply:
    text: str
    buttons: list = field(default_factory=list)  # ряды кнопок [(текст, callback_data)]
    notify: list = field(default_factory=list)   # [(id игрока, текст)]


def locked(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper


def hp_bar(current, maximum, width=10):
    perc = max(0, current) / maximum if maximum else 0
    filled = max(1, round(perc * width)) if current > 0 else 0
    color = "🟩" if perc > 0.6 else "🟨" if perc > 0.25 else "🟥"
    return color * filled + "⬛" * (width - filled)


def pairs(buttons):
    """Раскладывает кнопки по две в ряд."""
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


class Game:
    def __init__(self, db_path="game.db", clock=time.time, invite_only=False, admins=()):
        self.lock = threading.RLock()
        self.clock = clock
        self.invite_only = invite_only
        self.admins = set(admins)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        for statement in SCHEMA:
            self.db.execute(statement)
        self.players = {}
        self.mobs = {}
        self._mob_ids = itertools.count(1)
        self.respawn_at = {}
        self.boss_respawn_at = {}
        self.chest_ready_at = {pos: 0.0 for pos in world.CHESTS}
        self._populate()

    # ================= мир =================

    def _populate(self):
        for pos, tile in world.iter_tiles():
            for _ in range(random.randint(1, tile.max_mobs) if tile.max_mobs else 0):
                self._spawn(pos, random.choice(tile.spawns))
        for pos, kind in world.BOSSES.items():
            self._spawn(pos, kind, boss=True)

    def _spawn(self, pos, kind, boss=False):
        mob = Mob(next(self._mob_ids), kind, pos, world.MOBS[kind].hp, boss)
        self.mobs[mob.id] = mob
        return mob

    def mobs_at(self, pos):
        return [m for m in self.mobs.values() if m.pos == pos]

    def _refresh(self, pos):
        """Ленивый респаун: монстры возвращаются, когда кто-то заглядывает в локацию."""
        now = self.clock()
        mobs = self.mobs_at(pos)
        boss = world.BOSSES.get(pos)
        if boss and not any(m.boss for m in mobs) and now >= self.boss_respawn_at.get(pos, 0):
            self._spawn(pos, boss, boss=True)
        tile = world.tile_at(pos)
        if sum(not m.boss for m in mobs) < tile.max_mobs and now >= self.respawn_at.get(pos, 0):
            self._spawn(pos, random.choice(tile.spawns))
            self.respawn_at[pos] = now + MOB_RESPAWN

    # ================= игроки и база =================

    def _load(self, uid):
        row = self.db.execute("SELECT data FROM players WHERE id = ?", (uid,)).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        data["seen"] = {tuple(pos) for pos in data.get("seen", [])}
        known = {f.name for f in fields(Player)} - TRANSIENT - {"id"}
        return Player(uid, **{k: v for k, v in data.items() if k in known})

    def _save(self, p):
        data = {k: v for k, v in asdict(p).items() if k not in TRANSIENT}
        data["seen"] = sorted(p.seen)
        self.db.execute(
            "INSERT OR REPLACE INTO players (id, name, level, xp, kills, data) VALUES (?, ?, ?, ?, ?, ?)",
            (p.id, p.name, p.level, p.xp, p.kills, json.dumps(data, ensure_ascii=False)))
        self.db.commit()

    def _get(self, uid):
        p = self.players.get(uid) or self._load(uid)
        if p is None:
            locked_out = self.invite_only and uid not in self.admins
            p = Player(uid, stage="invite" if locked_out else "name")
            self._reveal(p)
            self._save(p)
        self.players[uid] = p
        now = self.clock()
        p.last_seen = now
        self._regen(p, now)
        return p

    def _regen(self, p, now):
        if p.hp >= p.max_hp:
            p.hp = p.max_hp
            p.regen_at = now
            return
        ticks = int((now - p.regen_at) // REGEN_EVERY)
        if ticks > 0:
            p.hp = min(p.max_hp, p.hp + ticks)
            p.regen_at += ticks * REGEN_EVERY

    def _reveal(self, p):
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            pos = (p.x + dx, p.y + dy)
            if world.in_bounds(pos):
                p.seen.add(pos)

    def _online(self):
        now = self.clock()
        return [p for p in self.players.values()
                if p.stage == "play" and now - p.last_seen < ACTIVE_WINDOW]

    def _others_here(self, p):
        return [o for o in self._online() if o.id != p.id and o.pos == p.pos]

    def _give(self, p, item_id, n=1):
        item = ITEMS[item_id]
        if p.bag_count + n > BAG_SIZE:
            return f"🎒 Рюкзак полон — {item.label} пришлось оставить."
        p.bag[item_id] = p.bag.get(item_id, 0) + n
        return f"🎁 {item.label}" + (f" ×{n}" if n > 1 else "")

    @staticmethod
    def _take(p, item_id, n=1):
        p.bag[item_id] -= n
        if p.bag[item_id] <= 0:
            del p.bag[item_id]

    @staticmethod
    def _status(p):
        return f"❤️ {p.hp}/{p.max_hp}   ⭐ ур. {p.level} ({p.xp}/{p.xp_needed})   💰 {p.gold}"

    def _gain_xp(self, p, base_xp):
        xp = round(base_xp * (1 + 0.03 * p.stat("int")))
        p.xp += xp
        log = []
        while p.xp >= p.xp_needed:
            p.xp -= p.xp_needed
            p.level += 1
            p.points += POINTS_PER_LEVEL
            p.hp = p.max_hp
            log.append(f"🎉 Новый уровень: {p.level}! +{POINTS_PER_LEVEL} очка характеристик "
                       "(распредели в 📜 Герой).")
        return xp, log

    def _die(self, p):
        lost = int(p.gold * DEATH_GOLD_LOSS)
        p.gold -= lost
        p.x, p.y = world.CAMP
        p.hp = p.max_hp // 2
        p.regen_at = self.clock()
        p.fighting = 0
        return ["", "💀 Ты погиб..." + (f" Потеряно {lost} 💰." if lost else ""),
                "Тебя притащили в лагерь. Отдохни у костра."]

    # ================= бой =================

    def _engaged(self, p):
        mob = self.mobs.get(p.fighting)
        return mob if mob and mob.pos == p.pos else None

    def _player_turn(self, p, mob):
        t = mob.type
        w = p.weapon_item
        perk = w.perk if w.perk and random.random() < p.perk_chance else ""
        defense = 0 if perk == "pierce" else t.defense
        dmg = max(1, round(p.base_damage + random.randint(-1, 1) - defense))
        crit = perk == "crit" or random.random() < p.crit_chance
        if crit:
            dmg *= 3 if perk == "crit" else 2
        if perk == "double":
            dmg += max(1, dmg // 2)
        mob.hp -= dmg
        mob.damage_by[p.id] = mob.damage_by.get(p.id, 0) + dmg
        text = f"{'💥 Крит! ' if crit else ''}Ты бьёшь: {t.name} −{dmg} ❤️"
        if perk:
            text += f" ({PERKS[perk]})"
        return [text], perk == "stun"

    def _mob_turn(self, p, mob):
        t = mob.type
        if random.random() < p.dodge_chance:
            return [f"💨 Ты увернулся от удара: {t.name}."]
        dmg = max(1, t.attack - p.defense + random.randint(-1, 1))
        crit = random.random() < 0.1
        if crit:
            dmg *= 2
        p.hp -= dmg
        return [f"{'💥 ' if crit else ''}{t.emoji} {t.name} бьёт тебя: −{dmg} ❤️"]

    def _kill(self, mob, killer, notify):
        t = mob.type
        del self.mobs[mob.id]
        if mob.boss:
            self.boss_respawn_at[mob.pos] = self.clock() + BOSS_RESPAWN
        else:
            self.respawn_at[mob.pos] = self.clock() + MOB_RESPAWN

        gold = random.randint(*t.gold)
        killer.gold += gold
        killer.kills += 1
        killer.fighting = 0
        xp, level_log = self._gain_xp(killer, t.xp)
        log = [f"☠️ {t.name} повержен! +{xp} опыта" + (f", +{gold} 💰" if gold else "")]
        log += [self._give(killer, item_id) for item_id, chance in t.loot
                if random.random() < chance]
        log += level_log

        # Все, кто помогал в бою, тоже получают опыт.
        for pid in mob.damage_by:
            ally = self.players.get(pid)
            if pid == killer.id or ally is None:
                continue
            ally_xp, ally_log = self._gain_xp(ally, t.xp)
            self._save(ally)
            notify.append((pid, "\n".join(
                [f"🤝 {killer.name} добил: {t.name}. Тебе +{ally_xp} опыта за помощь."] + ally_log)))

        if mob.boss:
            for o in self._online():
                if o.id != killer.id and o.id not in mob.damage_by:
                    notify.append((o.id, f"📯 {killer.name} одолел босса: {mob.label}!"))
        return log

    def _ambush(self, p, header):
        """Агрессивные монстры могут напасть первыми. Возвращает Reply или None."""
        self._refresh(p.pos)
        attackers = [m for m in self.mobs_at(p.pos) if m.type.aggressive]
        if not attackers or random.random() >= AMBUSH_CHANCE:
            return None
        mob = random.choice(attackers)
        p.fighting = mob.id
        log = header + [f"⚠️ Засада! {mob.label} нападает первым!"] + self._mob_turn(p, mob)
        if p.hp <= 0:
            log += self._die(p)
            self._save(p)
            return self._describe(p, "\n".join(log))
        self._save(p)
        return self._combat_view(p, mob, log)

    # ================= экраны =================

    def _describe(self, p, header=""):
        self._refresh(p.pos)
        tile = world.tile_at(p.pos)
        lines = [header, ""] if header else []
        lines.append(f"{tile.emoji} {tile.name} ({p.x}, {p.y})")
        lines.append(tile.descriptions[(p.x * 7 + p.y * 13) % len(tile.descriptions)])
        buttons = []

        others = self._others_here(p)
        if others:
            lines.append("👥 Рядом: " + ", ".join(o.name for o in others))

        mobs = self.mobs_at(p.pos)
        if mobs:
            lines += ["", "⚔️ Враги:"]
            for m in mobs:
                lines.append(f"  {m.label} — ❤️ {m.hp}/{m.type.hp}")
                buttons.append([(f"⚔️ {m.label} {m.hp}/{m.type.hp}", f"atk:{m.id}")])
        elif not tile.safe:
            lines.append("Врагов не видно.")

        if p.pos in world.CHESTS:
            wait = self.chest_ready_at[p.pos] - self.clock()
            if wait <= 0:
                lines.append("🧰 Здесь стоит сундук!")
                buttons.append([("🧰 Открыть сундук", "chest")])
            else:
                lines.append(f"🧰 Сундук пуст. Снова наполнится через {math.ceil(wait / 60)} мин.")

        gathering = world.GATHERING.get(world.tile_key(p.pos))
        if gathering:
            buttons.append([(gathering[0], "gather")])

        if tile.safe:
            buttons.append([("🛌 Отдохнуть", "rest"), ("🛒 Торговец", "shop")])

        lines += ["", self._status(p)]
        row = [("🔄 Обновить", "look")]
        if p.bag.get("potion") and p.hp < p.max_hp:
            row.insert(0, (f"🧪 Зелье ({p.bag['potion']})", "use:potion:look"))
        buttons.append(row)
        return Reply("\n".join(lines), buttons)

    def _combat_view(self, p, mob, log):
        t = mob.type
        tile = world.tile_at(p.pos)
        lines = [f"{tile.emoji} {tile.name} ({p.x}, {p.y})", ""] + log + [
            "━━━━━━━━━━━━━",
            f"👾 {mob.label}", f"{hp_bar(mob.hp, t.hp)} {mob.hp}/{t.hp}",
            f"👤 {p.name}", f"{hp_bar(p.hp, p.max_hp)} {p.hp}/{p.max_hp}",
        ]
        row = [("🏃 Сбежать", "flee")]
        if p.bag.get("potion"):
            row.insert(0, (f"🧪 Зелье ({p.bag['potion']})", f"use:potion:{mob.id}"))
        return Reply("\n".join(lines), [[("⚔️ Атаковать", f"atk:{mob.id}")], row])

    def _context_view(self, p, ctx, note):
        if ctx == "bag":
            return self._bag_view(p, note)
        if ctx.isdigit():
            mob = self.mobs.get(int(ctx))
            if mob and mob.pos == p.pos:
                return self._combat_view(p, mob, [note])
        return self._describe(p, note)

    def _stats_view(self, p, header=""):
        creating = p.stage == "stats"
        lines = [header, ""] if header else []
        lines += [
            "Распредели очки характеристик:" if creating else "✨ Прокачка характеристик",
            f"Свободных очков: {p.points}", "",
            "💪 Сила — урон тяжёлым оружием и здоровье",
            "💨 Ловкость — урон лёгким оружием, уклонение и побег",
            "🍀 Удача — криты и срабатывание перков оружия",
            "🧠 Интеллект — урон посохами, опыт и сила лечения",
        ]
        buttons = []
        for key in STATS:
            row = []
            if creating:
                row.append(("➖", f"s-:{key}") if p.stats[key] > 1 else ("🚫", "noop"))
            row.append((f"{STAT_NAMES[key]}: {p.stats[key]}", "noop"))
            row.append(("➕", f"s+:{key}") if p.points else ("✖️", "noop"))
            buttons.append(row)
        if creating:
            buttons.append([("✅ Начать приключение", "sdone")] if not p.points
                           else [(f"Осталось распределить: {p.points}", "noop")])
        else:
            buttons.append([("⬅️ Назад", "hero")])
        return Reply("\n".join(lines), buttons)

    def _hero_view(self, p):
        tile = world.tile_at(p.pos)
        lines = [
            f"📜 {p.name}",
            f"⭐ Уровень {p.level} ({p.xp}/{p.xp_needed} опыта)",
            f"❤️ {hp_bar(p.hp, p.max_hp)} {p.hp}/{p.max_hp}",
            "",
            f"💪 Сила {p.stat('str')}   💨 Ловкость {p.stat('dex')}",
            f"🍀 Удача {p.stat('luck')}   🧠 Интеллект {p.stat('int')}",
            "",
            f"⚔️ Урон ~{round(p.base_damage)}   🛡 Защита {p.defense}",
            f"💥 Крит {round(p.crit_chance * 100)}%   💨 Уклонение {round(p.dodge_chance * 100)}%",
            f"🗡 {p.weapon_item.label}",
            "",
            f"💰 {p.gold}   ☠️ Побед: {p.kills}",
            f"📍 {tile.emoji} {tile.name} ({p.x}, {p.y})",
        ]
        buttons = [[(f"✨ Распределить очки ({p.points})", "stats")]] if p.points else []
        buttons.append([("🎒 Рюкзак", "bag"), ("🛡 Снаряжение", "gear")])
        return Reply("\n".join(lines), buttons)

    def _bag_view(self, p, note=""):
        lines = [note, ""] if note else []
        lines.append(f"🎒 Рюкзак: {p.bag_count}/{BAG_SIZE}   💰 {p.gold}")
        lines.append("Нажми на предмет, чтобы использовать, надеть или продать."
                     if p.bag else "Пусто.")
        kinds = ("food", "book", "weapon", "armor", "ring", "amulet", "trash")
        items = sorted(p.bag.items(), key=lambda kv: (kinds.index(ITEMS[kv[0]].kind), ITEMS[kv[0]].name))
        buttons = pairs([(ITEMS[i].label + (f" ×{n}" if n > 1 else ""), f"inv:{i}") for i, n in items])
        buttons.append([("🛡 Снаряжение", "gear"), ("⬅️ Назад", "look")])
        return Reply("\n".join(lines), buttons)

    def _gear_view(self, p, note=""):
        lines = [note, ""] if note else []
        lines += ["🛡 Снаряжение", ""]
        buttons = []
        for slot, label in EQUIP_SLOTS.items():
            item = ITEMS.get(getattr(p, slot))
            if item:
                lines.append(f"{label}: {item.label} — {item.describe()}")
                buttons.append([(f"❌ Снять: {item.label}", f"uneq:{slot}")])
            else:
                lines.append(f"{label}: " + (f"{FISTS.label} — {FISTS.describe()}" if slot == "weapon" else "—"))
        buttons.append([("🎒 Рюкзак", "bag"), ("⬅️ Назад", "look")])
        return Reply("\n".join(lines), buttons)

    def _shop_view(self, p, note=""):
        lines = [note, ""] if note else []
        lines += ["🛒 Торговец: «Чего желаешь, путник?»", f"💰 У тебя: {p.gold}", ""]
        for item_id in SHOP:
            item = ITEMS[item_id]
            lines.append(f"{item.label} — {item.value}💰 ({item.describe()})")
        lines += ["", "Продать трофеи можно через 🎒 Рюкзак."]
        buttons = pairs([(f"Купить {ITEMS[i].label}", f"buy:{i}") for i in SHOP])
        buttons.append([("🎒 Рюкзак", "bag"), ("⬅️ Назад", "look")])
        return Reply("\n".join(lines), buttons)

    # ================= создание героя =================

    @locked
    def stage(self, uid):
        p = self._get(uid)
        if p.stage == "invite" and (uid in self.admins or not self.invite_only):
            p.stage = "name"
            self._save(p)
        return p.stage

    @locked
    def redeem(self, uid, code):
        p = self._get(uid)
        if p.stage != "invite":
            return Reply("Код уже не нужен.")
        deleted = self.db.execute("DELETE FROM invite_codes WHERE code = ?", (code.strip().upper(),))
        if not deleted.rowcount:
            return Reply("❌ Неверный код. Попробуй ещё раз или попроси код у администратора.")
        p.stage = "name"
        self._save(p)
        return Reply("✅ Доступ открыт!\n\n✨ Как будут звать твоего героя? (2–16 символов)")

    @locked
    def set_name(self, uid, name):
        p = self._get(uid)
        name = " ".join(name.split())
        if not NAME_RE.fullmatch(name):
            return Reply("⚠️ Имя: 2–16 символов — буквы, цифры, пробел, _ или -. Попробуй ещё раз:")
        key = name.casefold()
        for (other,) in self.db.execute("SELECT name FROM players WHERE id != ?", (uid,)):
            if other and other.casefold() == key:
                return Reply("Это имя уже занято. Придумай другое:")
        p.name = name
        p.stage = "stats"
        self._save(p)
        return self._stats_view(p, f"⚔️ Герой {name}! У тебя {p.points} очков.")

    @locked
    def stats(self, uid):
        return self._stats_view(self._get(uid))

    @locked
    def change_stat(self, uid, key, delta):
        p = self._get(uid)
        if key in STATS:
            if delta > 0 and p.points > 0:
                p.stats[key] += 1
                p.points -= 1
            elif delta < 0 and p.stage == "stats" and p.stats[key] > 1:
                p.stats[key] -= 1
                p.points += 1
            self._save(p)
        return self._stats_view(p)

    @locked
    def finish_creation(self, uid):
        """Возвращает приветствие или None, если очки ещё не распределены."""
        p = self._get(uid)
        if p.stage != "stats" or p.points:
            return None
        p.stage = "play"
        p.hp = p.max_hp
        p.regen_at = self.clock()
        self._save(p)
        return Reply(f"✅ {p.name} готов к приключениям!\n\n{INTRO}")

    # ================= действия в мире =================

    @locked
    def online_count(self):
        return len(self._online())

    @locked
    def look(self, uid):
        p = self._get(uid)
        mob = self._engaged(p)
        if mob:
            return self._combat_view(p, mob, ["Ты в бою!"])
        return self._describe(p)

    @locked
    def move(self, uid, dx, dy):
        p = self._get(uid)
        target = (p.x + dx, p.y + dy)
        if not world.in_bounds(target):
            return Reply("🌫 Дальше край мира — только туман и пустота. Выбери другое направление.")
        tile = world.tile_at(target)
        if not tile.passable:
            return Reply(f"{tile.emoji} {tile.blocked}")

        header = []
        mob = self._engaged(p)
        if mob:
            if random.random() >= p.flee_chance:
                log = ["🏃 Ты пытаешься уйти, но враг не отпускает!"] + self._mob_turn(p, mob)
                if p.hp <= 0:
                    log += self._die(p)
                    self._save(p)
                    return self._describe(p, "\n".join(log))
                self._save(p)
                return self._combat_view(p, mob, log)
            header.append("💨 Ты вырвался из боя!")
        p.fighting = 0
        p.came_from = p.pos
        p.x, p.y = target
        self._reveal(p)

        arrivals = [(o.id, f"👣 {p.name} пришёл сюда.") for o in self._others_here(p)]
        reply = self._ambush(p, header)
        if reply is None:
            self._save(p)
            reply = self._describe(p, "\n".join(header))
        reply.notify += arrivals
        return reply

    @locked
    def attack(self, uid, mob_id):
        p = self._get(uid)
        mob = self.mobs.get(mob_id)
        if mob is None or mob.pos != p.pos:
            p.fighting = 0
            return self._describe(p, "Этого врага здесь уже нет.")
        p.fighting = mob.id
        log, stunned = self._player_turn(p, mob)

        if mob.hp <= 0:
            notify = []
            log += self._kill(mob, p, notify)
            self._save(p)
            reply = self._describe(p, "\n".join(log))
            reply.notify = notify
            return reply

        if stunned:
            log.append(f"💫 {mob.type.name} оглушён и пропускает ход!")
        else:
            log += self._mob_turn(p, mob)
        if p.hp <= 0:
            log += self._die(p)
            self._save(p)
            return self._describe(p, "\n".join(log))
        self._save(p)
        return self._combat_view(p, mob, log)

    @locked
    def flee(self, uid):
        p = self._get(uid)
        mob = self._engaged(p)
        if mob is None:
            p.fighting = 0
            return self._describe(p)
        if random.random() < p.flee_chance:
            p.fighting = 0
            p.x, p.y = p.came_from
            self._save(p)
            return self._describe(p, f"💨 Ты сбежал от врага ({mob.label}) туда, откуда пришёл.")
        log = ["🏃 Сбежать не удалось!"] + self._mob_turn(p, mob)
        if p.hp <= 0:
            log += self._die(p)
            self._save(p)
            return self._describe(p, "\n".join(log))
        self._save(p)
        return self._combat_view(p, mob, log)

    @locked
    def open_chest(self, uid):
        p = self._get(uid)
        tier_id = world.CHESTS.get(p.pos)
        if tier_id is None:
            return self._describe(p, "Здесь нет сундука.")
        if self.clock() < self.chest_ready_at[p.pos]:
            return self._describe(p, "Сундук пуст — кто-то успел раньше.")
        self._refresh(p.pos)
        if self.mobs_at(p.pos):
            return self._describe(p, "🛡 Сундук охраняют враги — сначала победи их!")

        tier = world.CHEST_TIERS[tier_id]
        self.chest_ready_at[p.pos] = self.clock() + CHEST_RESPAWN
        gold = random.randint(*tier.gold)
        p.gold += gold
        log = [f"🧰 Ты открываешь {tier.name}!", f"💰 +{gold} золота"]
        log += [self._give(p, random.choice(tier.pool)) for _ in range(tier.rolls)]
        self._save(p)
        return self._describe(p, "\n".join(log))

    @locked
    def gather(self, uid):
        p = self._get(uid)
        gathering = world.GATHERING.get(world.tile_key(p.pos))
        if gathering is None:
            return self._describe(p, "Здесь нечего добывать.")
        wait = p.gather_at - self.clock()
        if wait > 0:
            return self._describe(p, f"Ты устал. Попробуй снова через {math.ceil(wait)} сек.")
        p.gather_at = self.clock() + world.GATHER_COOLDOWN
        _, item_id, chance, fail_text = gathering
        note = self._give(p, item_id) if random.random() < chance else fail_text
        reply = self._ambush(p, [note, "Шум привлёк внимание!"])
        if reply:
            return reply
        self._save(p)
        return self._describe(p, note)

    @locked
    def rest(self, uid):
        p = self._get(uid)
        if not world.tile_at(p.pos).safe:
            return self._describe(p, "Отдыхать безопасно только в лагере.")
        p.hp = p.max_hp
        self._save(p)
        return self._describe(p, "🛌 Ты отдохнул у костра. Здоровье восстановлено.")

    # ================= рюкзак и снаряжение =================

    @locked
    def hero(self, uid):
        return self._hero_view(self._get(uid))

    @locked
    def bag(self, uid):
        return self._bag_view(self._get(uid))

    @locked
    def gear(self, uid):
        return self._gear_view(self._get(uid))

    @locked
    def item(self, uid, item_id):
        p = self._get(uid)
        n = p.bag.get(item_id, 0)
        if not n:
            return self._bag_view(p, "Этого предмета уже нет.")
        item = ITEMS[item_id]
        lines = [item.label + (f" ×{n}" if n > 1 else ""), item.describe()]
        buttons = []
        if item.kind in EQUIP_SLOTS:
            current = ITEMS.get(getattr(p, item.kind))
            if item.kind == "weapon":
                current = current or FISTS
            lines.append("Сейчас надето: " + (f"{current.label} — {current.describe()}" if current else "ничего"))
            buttons.append([("✅ Надеть", f"eq:{item_id}")])
        elif item.kind in ("food", "book"):
            buttons.append([("✨ Использовать", f"use:{item_id}:bag")])
        if item.sell_price:
            if world.tile_at(p.pos).safe:
                buttons.append([(f"💰 Продать за {item.sell_price}", f"sell:{item_id}")])
            else:
                lines.append(f"Торговец в лагере купит за {item.sell_price} 💰")
        buttons.append([("🗑 Выбросить", f"drop:{item_id}"), ("⬅️ Назад", "bag")])
        return Reply("\n".join(lines), buttons)

    @locked
    def use(self, uid, item_id, ctx="look"):
        p = self._get(uid)
        item = ITEMS.get(item_id)
        if item is None or not p.bag.get(item_id):
            note = "Такого предмета нет в рюкзаке."
        elif item.kind == "food":
            if p.hp >= p.max_hp:
                note = "Ты и так полон сил."
            else:
                heal = min(round(item.heal * (1 + 0.05 * p.stat("int"))), p.max_hp - p.hp)
                p.hp += heal
                self._take(p, item_id)
                note = f"{item.label}: +{heal} ❤️"
        elif item.kind == "book":
            key, bonus = item.stat
            p.stats[key] += bonus
            self._take(p, item_id)
            note = f"{item.emoji} Ты изучил «{item.name}»: {STAT_NAMES[key]} +{bonus} навсегда!"
        else:
            note = "Это нельзя использовать."
        self._save(p)
        return self._context_view(p, ctx, note)

    @locked
    def equip(self, uid, item_id):
        p = self._get(uid)
        item = ITEMS.get(item_id)
        if item is None or not p.bag.get(item_id) or item.kind not in EQUIP_SLOTS:
            return self._bag_view(p, "Это нельзя надеть.")
        old = getattr(p, item.kind)
        self._take(p, item_id)
        if old:
            p.bag[old] = p.bag.get(old, 0) + 1
        setattr(p, item.kind, item_id)
        p.hp = min(p.hp, p.max_hp)
        self._save(p)
        return self._bag_view(p, f"✅ Надето: {item.label}")

    @locked
    def unequip(self, uid, slot):
        p = self._get(uid)
        if slot not in EQUIP_SLOTS or not getattr(p, slot):
            return self._gear_view(p)
        if p.bag_count >= BAG_SIZE:
            return self._gear_view(p, "🎒 Рюкзак полон — снять некуда.")
        item_id = getattr(p, slot)
        setattr(p, slot, "")
        p.bag[item_id] = p.bag.get(item_id, 0) + 1
        p.hp = min(p.hp, p.max_hp)
        self._save(p)
        return self._gear_view(p, f"📦 Снято: {ITEMS[item_id].label}")

    @locked
    def drop(self, uid, item_id):
        p = self._get(uid)
        if not p.bag.get(item_id):
            return self._bag_view(p)
        self._take(p, item_id)
        self._save(p)
        return self._bag_view(p, f"🗑 Выброшено: {ITEMS[item_id].label}")

    # ================= торговец =================

    @locked
    def shop(self, uid):
        p = self._get(uid)
        if not world.tile_at(p.pos).safe:
            return self._describe(p, "Торговец ждёт тебя в лагере.")
        return self._shop_view(p)

    @locked
    def buy(self, uid, item_id):
        p = self._get(uid)
        if not world.tile_at(p.pos).safe:
            return self._describe(p, "Торговец ждёт тебя в лагере.")
        if item_id not in SHOP:
            return self._shop_view(p, "Такого товара нет.")
        item = ITEMS[item_id]
        if p.gold < item.value:
            return self._shop_view(p, f"Не хватает золота: нужно {item.value} 💰.")
        if p.bag_count >= BAG_SIZE:
            return self._shop_view(p, "🎒 Рюкзак полон.")
        p.gold -= item.value
        self._give(p, item_id)
        self._save(p)
        return self._shop_view(p, f"✅ Куплено: {item.label}")

    @locked
    def sell(self, uid, item_id):
        p = self._get(uid)
        item = ITEMS.get(item_id)
        if not world.tile_at(p.pos).safe:
            return self._bag_view(p, "Продавать можно только торговцу в лагере.")
        if item is None or not p.bag.get(item_id) or not item.sell_price:
            return self._bag_view(p, "Это не продать.")
        self._take(p, item_id)
        p.gold += item.sell_price
        self._save(p)
        return self._bag_view(p, f"💰 Продано: {item.label} за {item.sell_price}")

    # ================= общее =================

    @locked
    def world_map(self, uid):
        p = self._get(uid)
        rows, legend = [], {}
        for y in range(world.RADIUS, -world.RADIUS - 1, -1):
            row = ""
            for x in range(-world.RADIUS, world.RADIUS + 1):
                if (x, y) == p.pos:
                    row += "🧍"
                elif (x, y) in p.seen:
                    tile = world.tile_at((x, y))
                    legend[tile.emoji] = tile.name
                    row += tile.emoji
                else:
                    row += "⬛"
            rows.append(row)
        legend_text = "\n".join(f"{e} {n}" for e, n in legend.items())
        return Reply("🗺 Карта (север сверху)\n\n" + "\n".join(rows)
                     + "\n\n🧍 Ты   ⬛ Неизведано\n" + legend_text)

    @locked
    def top(self):
        rows = self.db.execute(
            "SELECT name, level, kills FROM players WHERE name != '' "
            "ORDER BY level DESC, xp DESC LIMIT 10").fetchall()
        if not rows:
            return Reply("Пока никто не играет.")
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 Лучшие герои:", ""]
        for i, (name, level, kills) in enumerate(rows):
            lines.append(f"{medals[i] if i < 3 else f'{i + 1}.'} {name} — ур. {level}, побед: {kills}")
        return Reply("\n".join(lines))

    @locked
    def say(self, uid, text):
        p = self._get(uid)
        text = text.strip()[:300]
        others = self._others_here(p)
        if not others:
            return Reply("Рядом никого нет — тебя слышит только ветер. 🍃\n"
                         "Сообщения видят игроки в той же локации.")
        return Reply(f"💬 Ты: {text}", notify=[(o.id, f"💬 {p.name}: {text}") for o in others])

    # ================= админ =================

    @locked
    def admin_stats(self):
        total = self.db.execute("SELECT COUNT(*) FROM players WHERE name != ''").fetchone()[0]
        codes = self.db.execute("SELECT COUNT(*) FROM invite_codes").fetchone()[0]
        return Reply("\n".join([
            "🛠 Админ-панель",
            f"👥 Героев в базе: {total}, в сети: {len(self._online())}",
            f"👾 Монстров в мире: {len(self.mobs)}",
            f"🎟 Неиспользованных инвайтов: {codes}" + (" (вход по инвайтам)" if self.invite_only else ""),
            "",
            "/gen — создать инвайт-код",
            "/give <предмет> [кол-во] — выдать себе (gold — золото)",
            "/items — список предметов",
            "/backup — прислать файл базы",
        ]))

    @locked
    def new_invite(self):
        code = "RPG-" + "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
        self.db.execute("INSERT INTO invite_codes (code) VALUES (?)", (code,))
        self.db.commit()
        return code

    @locked
    def give(self, uid, item_id, n=1):
        p = self._get(uid)
        if item_id == "gold":
            p.gold += n
        elif item_id in ITEMS:
            p.bag[item_id] = p.bag.get(item_id, 0) + n
        else:
            return Reply("Нет такого предмета. Список: /items")
        self._save(p)
        return Reply(f"✅ Выдано: {item_id} ×{n}")

    @locked
    def backup(self, path):
        dst = sqlite3.connect(path)
        try:
            self.db.backup(dst)
        finally:
            dst.close()

