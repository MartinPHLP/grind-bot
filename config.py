import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
FEED_CHANNEL_ID = int(os.getenv("FEED_CHANNEL_ID", "0"))
SUIVI_CHANNEL_ID = int(os.getenv("SUIVI_CHANNEL_ID", "0"))

TZ = "Europe/Paris"
DB_PATH = "grind.db"

# Nombre max d'objectifs par semaine (limite technique : un formulaire
# Discord accepte 5 champs max, 1 est reservé à la motivation)
MAX_OBJECTIVES = 10

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant dans le fichier .env")
if GUILD_ID == 0 or FEED_CHANNEL_ID == 0 or SUIVI_CHANNEL_ID == 0:
    raise RuntimeError("GUILD_ID / FEED_CHANNEL_ID / SUIVI_CHANNEL_ID manquant(s) dans le fichier .env")