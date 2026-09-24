# Приграничье — MMO RPG в Telegram

Общий мир для всех игроков: карта 11×11, орки, бандиты, гоблины и звери, боссы, сундуки,
разрушенная башня, старые шахты, пруд и река.

## Что есть в игре

- **Герой**: имя и 10 очков на характеристики (💪 сила, 💨 ловкость, 🍀 удача, 🧠 интеллект),
  +2 очка за каждый уровень.
- **Мир** ([game/world.py](game/world.py)): лагерь в центре, леса, луга, холмы, болото,
  разрушенная башня, старые шахты, пруд, река с двумя мостами, выжженные земли орков, логово бандитов.
- **Монстры** общие для всех: убил ты — пропал и у других. Возвращаются со временем.
  Волки, гоблины, бандиты и орки нападают сами.
- **Боссы**: Король гоблинов (шахты), Вождь орков, Главарь бандитов. Опыт получает каждый, кто бил.
- **8 сундуков**, их охраняют монстры. Добычу забирает первый, сундук наполняется через 15 минут.
- **Снаряжение** ([game/items.py](game/items.py)): оружие с перками (двойной удар, крит,
  пробой брони, оглушение), броня, кольца, амулеты, еда, книги и трофеи.
- **Торговец** в лагере: покупка и продажа. **Добыча**: руда в шахтах, рыба на пруду.
- **MMO**: видно, кто рядом, чат с игроками в той же локации, общие бои, рейтинг `/top`.
- **Админ** (`ADMIN_IDS`): `/admin`, `/gen` (инвайт-коды), `/give`, `/items`, `/backup`.

## Запуск на своём компьютере

```bash
pip install -r requirements.txt
cp .env.example .env      # и впиши BOT_TOKEN
python bot.py
```

Тесты: `python -m unittest`

## Запуск на сервере (Ubuntu/Debian VPS)

### Вариант 1: Docker (проще всего)

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
git clone https://github.com/Ilyas-GR/Game.git /opt/gamebot
cd /opt/gamebot
cp .env.example .env && nano .env         # впиши BOT_TOKEN и ADMIN_IDS
sudo docker compose up -d --build
sudo docker compose logs -f               # посмотреть логи
```

База лежит в `/opt/gamebot/data/game.db` и не пропадает при перезапуске.
Обновление: `git pull && sudo docker compose up -d --build`.

### Вариант 2: без Docker (systemd)

```bash
sudo apt update && sudo apt install -y python3-venv git
sudo useradd -r -m -d /opt/gamebot gamebot
sudo -u gamebot git clone https://github.com/Ilyas-GR/Game.git /opt/gamebot
cd /opt/gamebot
sudo -u gamebot python3 -m venv venv
sudo -u gamebot venv/bin/pip install -r requirements.txt
sudo -u gamebot cp .env.example .env && sudo -u gamebot nano .env
sudo cp deploy/gamebot.service /etc/systemd/system/
sudo systemctl enable --now gamebot
journalctl -u gamebot -f                  # логи
```

Обновление: `cd /opt/gamebot && sudo -u gamebot git pull && sudo systemctl restart gamebot`.

⚠️ Один токен может работать только в одной копии бота. Если бот запущен где-то ещё
(на своём ПК, в GitHub Actions), будет ошибка `Conflict: terminated by other getUpdates request`.
