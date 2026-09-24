"""Каталог предметов: оружие, броня, украшения, еда, книги и трофеи."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    emoji: str
    kind: str            # weapon / armor / ring / amulet / food / book / trash
    value: int = 0       # цена у торговца (продать можно за половину)
    dmg: int = 0         # оружие: базовый урон
    scale: tuple = ()    # оружие: от каких характеристик растёт урон
    perk: str = ""       # оружие: double / crit / pierce / stun
    defense: int = 0     # броня
    stat: tuple = ()     # украшения и книги: (характеристика, бонус)
    heal: int = 0        # еда

    @property
    def label(self):
        return f"{self.emoji} {self.name}"

    @property
    def sell_price(self):
        return max(1, self.value // 2) if self.value else 0

    def describe(self):
        if self.kind == "weapon":
            stats = "+".join(STAT_NAMES[s] for s in self.scale)
            perk = f", перк: {PERKS[self.perk]}" if self.perk else ""
            return f"урон {self.dmg} + ½ ({stats}){perk}"
        if self.kind == "armor":
            return f"защита +{self.defense}"
        if self.kind in ("ring", "amulet"):
            return f"{STAT_NAMES[self.stat[0]]} +{self.stat[1]}, пока надето"
        if self.kind == "book":
            return f"навсегда {STAT_NAMES[self.stat[0]]} +{self.stat[1]}"
        if self.kind == "food":
            return f"лечит {self.heal} ❤️"
        return "трофей, можно продать торговцу"


STAT_NAMES = {"str": "💪 Сила", "dex": "💨 Ловкость", "luck": "🍀 Удача", "int": "🧠 Интеллект"}

PERKS = {
    "double": "💨 двойной удар",
    "crit": "⚔️ сокрушительный крит",
    "pierce": "🎯 пробивает броню",
    "stun": "💫 оглушение",
}

FISTS = Item("Кулаки", "✊", "weapon", dmg=2, scale=("str",))

ITEMS = {
    # --- оружие ---
    "rusty_shiv": Item("Ржавая заточка", "🔪", "weapon", 25, dmg=3, scale=("dex",), perk="double"),
    "broken_sword": Item("Сломанный меч", "🗡", "weapon", 40, dmg=4, scale=("str", "dex"), perk="crit"),
    "crooked_spear": Item("Кривое копьё", "🔱", "weapon", 40, dmg=4, scale=("dex",), perk="pierce"),
    "staff": Item("Немагический посох", "🦯", "weapon", 35, dmg=3, scale=("int",), perk="stun"),
    "short_sword": Item("Короткий меч", "⚔️", "weapon", 90, dmg=6, scale=("str", "dex"), perk="crit"),
    "battle_axe": Item("Боевой топор", "🪓", "weapon", 180, dmg=9, scale=("str",), perk="stun"),
    "goblin_dagger": Item("Гоблинский кинжал", "🗡", "weapon", 70, dmg=6, scale=("dex",), perk="double"),
    "shaman_staff": Item("Посох шамана", "🪄", "weapon", 120, dmg=8, scale=("int",), perk="stun"),
    "king_hammer": Item("Молот короля гоблинов", "🔨", "weapon", 260, dmg=12, scale=("str",), perk="stun"),
    "orc_cleaver": Item("Орочий тесак", "🪓", "weapon", 300, dmg=13, scale=("str",), perk="crit"),
    "bandit_sabre": Item("Сабля главаря", "⚔️", "weapon", 300, dmg=12, scale=("str", "dex"), perk="pierce"),
    # --- броня ---
    "rag_jacket": Item("Рваная куртка", "🧥", "armor", 20, defense=1),
    "leather_vest": Item("Кожаный жилет", "🦺", "armor", 45, defense=2),
    "chainmail": Item("Кольчуга", "⛓", "armor", 120, defense=4),
    "orc_armor": Item("Орочий панцирь", "🛡", "armor", 250, defense=6),
    # --- украшения ---
    "ring_str": Item("Кольцо силы", "💍", "ring", 80, stat=("str", 2)),
    "ring_luck": Item("Кольцо удачи", "💍", "ring", 80, stat=("luck", 3)),
    "amulet_dex": Item("Амулет ловкости", "📿", "amulet", 80, stat=("dex", 2)),
    "amulet_int": Item("Амулет мудреца", "📿", "amulet", 80, stat=("int", 2)),
    # --- еда ---
    "potion": Item("Зелье лечения", "🧪", "food", 15, heal=30),
    "meat": Item("Жареное мясо", "🍖", "food", 6, heal=12),
    "fish": Item("Карась", "🐟", "food", 5, heal=10),
    "garlic": Item("Чеснок", "🧄", "food", 2, heal=5),
    "apple": Item("Тухлое яблоко", "🍎", "food", 1, heal=2),
    # --- книги ---
    "old_book": Item("Старая книга", "📖", "book", 30, stat=("int", 1)),
    "torn_scroll": Item("Рваный свиток", "📜", "book", 30, stat=("luck", 1)),
    "war_manual": Item("Воинский устав", "📕", "book", 60, stat=("str", 1)),
    # --- трофеи ---
    "rusty_nail": Item("Ржавый гвоздь", "🔩", "trash", 2),
    "stone": Item("Тяжёлый камень", "🪨", "trash"),
    "wolf_pelt": Item("Волчья шкура", "🐺", "trash", 12),
    "goblin_ear": Item("Ухо гоблина", "👂", "trash", 8),
    "orc_tusk": Item("Клык орка", "🦷", "trash", 20),
    "gold_ore": Item("Золотая руда", "🪙", "trash", 30),
}

# Что продаёт торговец в лагере.
SHOP = ["potion", "meat", "rusty_shiv", "broken_sword", "crooked_spear", "staff",
        "short_sword", "battle_axe", "rag_jacket", "leather_vest", "chainmail"]

EQUIP_SLOTS = {"weapon": "🗡 Оружие", "armor": "👕 Броня", "ring": "💍 Кольцо", "amulet": "📿 Амулет"}
