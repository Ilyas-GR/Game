"""Мир игры: карта, типы местности, монстры, сундуки и снаряжение."""
from collections import namedtuple
from dataclasses import dataclass

# Карта 11x11. Верхняя строка — самый север (y = 5), нижняя — юг (y = -5).
# Слева направо x идёт от -5 до 5. Лагерь (C) — в центре, в точке (0, 0).
#
#   C лагерь     P луга        F лес            H холмы
#   M шахты      T башня       O пруд           S болото
#   ~ река       = мост        D земли орков    K лагерь орков
#   B логово бандитов
MAP_ROWS = [
    "MMHHFFFP~DD",  # y =  5
    "MMHFFFPP~DD",  # y =  4
    "HHFFFPPP~DK",  # y =  3
    "FFFFPPPP=DD",  # y =  2
    "TFFPPPPP~DD",  # y =  1
    "FFPPPCPP~PD",  # y =  0
    "FFPPPPPP~PP",  # y = -1
    "SSPPOPPP~PP",  # y = -2
    "SSSPPPPP=PB",  # y = -3
    "SSFFPPPP~BB",  # y = -4
    "SSFFFPPP~BB",  # y = -5
]
RADIUS = 5
CAMP = (0, 0)


@dataclass(frozen=True)
class Tile:
    name: str
    emoji: str
    descriptions: tuple
    spawns: tuple = ()  # какие монстры водятся (повторы = выше шанс)
    max_mobs: int = 0
    safe: bool = False
    blocked: str = ""  # если задано — пройти нельзя, это текст отказа

    @property
    def passable(self):
        return not self.blocked


TILES = {
    "C": Tile("Лагерь", "🏕", (
        "Костёр потрескивает, у палаток отдыхают путники. Здесь безопасно.",
    ), safe=True),
    "P": Tile("Луга", "🟩", (
        "Высокая трава колышется на ветру.",
        "Среди цветов жужжат пчёлы, вдали пасётся кто-то крупный.",
        "Тропинка петляет между невысоких холмиков.",
        "На горизонте видны дымки костров.",
    ), ("rabbit", "rabbit", "boar", "wolf"), 2),
    "F": Tile("Лес", "🌲", (
        "Высокие сосны закрывают небо.",
        "Под ногами хрустят ветки. Кто-то следит за тобой из чащи.",
        "Где-то неподалёку воет волк.",
        "На коре деревьев свежие следы когтей.",
    ), ("wolf", "wolf", "boar", "bear", "goblin"), 2),
    "H": Tile("Холмы", "⛰️", (
        "Каменистые холмы продувает холодный ветер.",
        "С вершины холма видно полкарты. Внизу мелькают тени.",
    ), ("goblin", "wolf", "bandit"), 2),
    "M": Tile("Старые шахты", "⛏️", (
        "Из тёмного штрека тянет сыростью. Ржавые рельсы уходят вглубь.",
        "Под ногами обломки вагонеток, на стенах — гоблинские метки.",
        "Где-то в глубине звенят кирки. Гоблины добывают чужое золото.",
        "Своды подпёрты гнилыми балками. Лучше не шуметь.",
    ), ("goblin", "goblin", "goblin_shaman", "bat"), 3),
    "T": Tile("Разрушенная башня", "🏚", (
        "Полуобвалившаяся башня древнего мага. Винтовая лестница обрывается "
        "в пустоту, на стенах тлеют странные руны.",
    ), ("bandit", "goblin_shaman", "bat"), 3),
    "O": Tile("Пруд", "💧", (
        "Тихий пруд, заросший камышом. В воде что-то большое квакает.",
    ), ("frog", "frog", "snake"), 2),
    "~": Tile("Река", "🌊", (
        "Быстрая холодная река.",
    ), blocked="Бурная река преграждает путь. Вплавь не перебраться — поищи мост."),
    "=": Tile("Старый мост", "🌉", (
        "Скрипучий деревянный мост. Внизу шумит река, а на досках — следы сапог.",
    ), ("bandit",), 1),
    "S": Tile("Болото", "🟫", (
        "Ноги вязнут в трясине, над водой клубится туман.",
        "Из болотных огней доносится гоблинский смех.",
    ), ("snake", "frog", "goblin"), 2),
    "D": Tile("Выжженные земли", "🟥", (
        "Земля выжжена, повсюду торчат орочьи тотемы из костей.",
        "Вдали бьют барабаны. Это территория орков.",
    ), ("orc", "orc", "wolf"), 2),
    "K": Tile("Лагерь орков", "🛖", (
        "Частокол из заострённых брёвен, у огромного костра жарится туша кабана. "
        "Орки не рады гостям.",
    ), ("orc",), 3),
    "B": Tile("Логово бандитов", "🏴", (
        "Палатки из краденой парусины, повсюду ящики с награбленным.",
        "Бандиты делят добычу и косо на тебя смотрят.",
    ), ("bandit", "bandit", "wolf"), 3),
}

MobType = namedtuple("MobType", "name emoji hp attack defense xp gold loot aggressive")

MOBS = {
    # животные
    "rabbit": MobType("Заяц", "🐇", 8, 1, 0, 4, (0, 1), (("meat", 0.3),), False),
    "bat": MobType("Летучая мышь", "🦇", 10, 3, 0, 5, (0, 1), (), True),
    "snake": MobType("Змея", "🐍", 14, 4, 0, 8, (0, 2), (), True),
    "frog": MobType("Гигантская жаба", "🐸", 16, 3, 0, 8, (0, 3), (("apple", 0.3),), False),
    "boar": MobType("Кабан", "🐗", 22, 4, 1, 12, (0, 3), (("meat", 0.6),), False),
    "wolf": MobType("Волк", "🐺", 20, 4, 1, 12, (0, 2), (("wolf_pelt", 0.5),), True),
    "bear": MobType("Медведь", "🐻", 45, 8, 2, 30, (0, 4), (("meat", 0.8), ("wolf_pelt", 0.3)), False),
    # гоблины
    "goblin": MobType("Гоблин", "👺", 24, 5, 1, 15, (3, 8),
                      (("goblin_ear", 0.5), ("garlic", 0.2), ("rusty_shiv", 0.08)), True),
    "goblin_shaman": MobType("Гоблин-шаман", "🧙", 30, 8, 1, 25, (6, 15),
                             (("old_book", 0.2), ("staff", 0.1), ("shaman_staff", 0.04)), True),
    "goblin_king": MobType("Король гоблинов", "👑", 90, 11, 3, 90, (40, 80),
                           (("king_hammer", 0.4), ("ring_str", 0.3), ("gold_ore", 1.0)), False),
    # бандиты
    "bandit": MobType("Бандит", "🥷", 35, 7, 2, 25, (8, 18),
                      (("potion", 0.2), ("broken_sword", 0.08), ("rag_jacket", 0.08),
                       ("torn_scroll", 0.1)), True),
    "bandit_boss": MobType("Главарь бандитов", "🤠", 110, 13, 4, 120, (60, 120),
                           (("bandit_sabre", 0.4), ("amulet_dex", 0.3), ("potion", 1.0)), False),
    # орки
    "orc": MobType("Орк", "👹", 55, 10, 3, 40, (10, 25),
                   (("orc_tusk", 0.5), ("crooked_spear", 0.08), ("leather_vest", 0.08)), True),
    "orc_chief": MobType("Вождь орков", "💀", 150, 16, 5, 180, (80, 150),
                         (("orc_cleaver", 0.4), ("orc_armor", 0.4), ("ring_luck", 0.3)), False),
}

# Боссы всегда живут в своей локации и возвращаются после гибели.
BOSSES = {
    (-5, 5): "goblin_king",   # самая глубина шахт
    (5, 3): "orc_chief",      # лагерь орков
    (5, -5): "bandit_boss",   # логово бандитов
}

# Сундук: золото, сколько предметов достать и из какого набора.
ChestTier = namedtuple("ChestTier", "name gold rolls pool")

CHEST_TIERS = {
    "common": ChestTier("старый сундук", (5, 20), 2, (
        "potion", "potion", "garlic", "apple", "rusty_nail", "stone",
        "old_book", "torn_scroll", "rusty_shiv", "rag_jacket")),
    "rich": ChestTier("окованный сундук", (20, 50), 2, (
        "potion", "potion", "broken_sword", "crooked_spear", "staff", "leather_vest",
        "old_book", "torn_scroll", "war_manual", "gold_ore", "ring_str")),
    "epic": ChestTier("сундук с сокровищами", (60, 120), 3, (
        "potion", "potion", "short_sword", "battle_axe", "chainmail", "war_manual",
        "amulet_dex", "amulet_int", "ring_luck", "gold_ore")),
}

CHESTS = {
    (-5, 1): "rich",    # на вершине разрушенной башни
    (-4, 5): "rich",    # в глубине шахт
    (-1, -2): "common", # в камышах у пруда
    (-4, -4): "common", # в болоте
    (-2, 3): "common",  # в северном лесу
    (4, 4): "rich",     # на выжженных землях
    (5, 3): "epic",     # у шатра вождя орков
    (5, -5): "epic",    # в сокровищнице бандитов
}

# Добыча ресурсов: тип местности -> (кнопка, предмет, шанс, текст неудачи)
GATHERING = {
    "M": ("⛏ Добыть руду", "gold_ore", 0.35, "Кирка звенит о пустую породу."),
    "O": ("🎣 Рыбачить", "fish", 0.5, "Поплавок молчит. Рыба не клюёт."),
}
GATHER_COOLDOWN = 45  # сек.


def in_bounds(pos):
    return abs(pos[0]) <= RADIUS and abs(pos[1]) <= RADIUS


def tile_key(pos):
    x, y = pos
    return MAP_ROWS[RADIUS - y][x + RADIUS]


def tile_at(pos):
    return TILES[tile_key(pos)]


def iter_tiles():
    for y in range(RADIUS, -RADIUS - 1, -1):
        for x in range(-RADIUS, RADIUS + 1):
            yield (x, y), tile_at((x, y))
