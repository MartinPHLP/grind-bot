import logging
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
import database as db
from views import (
    ObjectivesBuilderView,
    CarryOverView,
    CheckinButton,
    build_objectives_embed,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grindbot")

TZ = ZoneInfo(config.TZ)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)


def now_paris() -> datetime:
    return datetime.now(TZ)


async def get_or_create_thread(member: discord.Member) -> discord.Thread:
    """Récupère le thread perso du membre dans #suivi-perso, ou le crée s'il n'existe pas."""
    thread_id = db.get_thread(member.id)
    if thread_id:
        thread = bot.get_channel(thread_id)
        if thread is None:
            try:
                thread = await bot.fetch_channel(thread_id)
            except discord.NotFound:
                thread = None
        if thread:
            return thread

    parent = bot.get_channel(config.SUIVI_CHANNEL_ID)
    thread = await parent.create_thread(
        name=f"suivi-{member.display_name}",
        type=discord.ChannelType.public_thread,
        auto_archive_duration=10080,  # 7 jours
    )
    await thread.add_user(member)
    db.set_thread(member.id, thread.id)
    return thread


# ---------------------------------------------------------------------------
# Commandes slash
# ---------------------------------------------------------------------------

@bot.tree.command(name="demarrer", description="Crée ton thread de suivi perso et pose tes premiers objectifs.")
async def demarrer(interaction: discord.Interaction):
    member = interaction.user
    thread = await get_or_create_thread(member)
    week_start = db.upcoming_week_start(now_paris().date())
    await interaction.response.send_message(
        f"C'est parti ! Ton thread perso : {thread.mention}\nClique ci-dessous pour poser tes objectifs.",
        ephemeral=True,
    )
    await thread.send(f"👋 Bienvenue {member.mention} !")
    builder = ObjectivesBuilderView(week_start, bot)
    await thread.send(embed=builder.build_embed(member.display_name), view=builder)


@bot.tree.command(name="objectifs", description="Poser/mettre à jour tes objectifs de la semaine à venir.")
async def objectifs(interaction: discord.Interaction):
    week_start = db.upcoming_week_start(now_paris().date())
    builder = ObjectivesBuilderView(week_start, bot)
    await interaction.response.send_message(
        embed=builder.build_embed(interaction.user.display_name), view=builder
    )


# ---------------------------------------------------------------------------
# Garde-fou : seul le propriétaire d'un thread de #suivi-perso peut y écrire
# ---------------------------------------------------------------------------

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if isinstance(message.channel, discord.Thread) and message.channel.parent_id == config.SUIVI_CHANNEL_ID:
        owner_thread_id = db.get_thread(message.author.id)
        if owner_thread_id != message.channel.id:
            try:
                await message.delete()
                await message.channel.send(
                    f"⚠️ {message.author.mention}, ce thread appartient à quelqu'un d'autre — "
                    f"chacun écrit uniquement dans le sien.",
                    delete_after=8,
                )
            except discord.Forbidden:
                pass
    await bot.process_commands(message)


# ---------------------------------------------------------------------------
# Tâches planifiées (heure de Paris, gère automatiquement l'heure d'été/hiver)
# ---------------------------------------------------------------------------

@tasks.loop(time=datetime.strptime("20:00", "%H:%M").time().replace(tzinfo=TZ))
async def sunday_reminder():
    """Dimanche 20h : rappel DM + thread si les objectifs de la semaine à venir ne sont pas postés."""
    if now_paris().weekday() != 6:
        return
    week_start = db.upcoming_week_start(now_paris().date())
    guild = bot.get_guild(config.GUILD_ID)
    for discord_id in db.get_all_users():
        if db.has_objectives(discord_id, week_start):
            continue
        member = guild.get_member(discord_id)
        if not member:
            continue
        thread_id = db.get_thread(discord_id)
        thread = bot.get_channel(thread_id) if thread_id else None
        try:
            await member.send(
                f"🔔 Pense à poser tes objectifs pour la semaine du {week_start} sur Grind Squad !"
            )
        except discord.Forbidden:
            pass
        if thread:
            await thread.send(f"🔔 {member.mention} objectifs de la semaine du **{week_start}** pas encore postés.")
            builder = ObjectivesBuilderView(week_start, bot)
            await thread.send(embed=builder.build_embed(member.display_name), view=builder)


@tasks.loop(time=datetime.strptime("09:00", "%H:%M").time().replace(tzinfo=TZ))
async def monday_relance():
    """Lundi 9h : si toujours rien, message neutre + gestion des oublis répétés."""
    if now_paris().weekday() != 0:
        return
    week_start = db.current_week_start(now_paris().date())
    previous_week = (date.fromisoformat(week_start) - timedelta(days=7)).isoformat()
    for discord_id in db.get_all_users():
        if db.has_objectives(discord_id, week_start):
            continue
        thread_id = db.get_thread(discord_id)
        thread = bot.get_channel(thread_id) if thread_id else None
        if not thread:
            continue
        db.increment_missed(discord_id)
        missed = db.get_missed(discord_id)
        member = thread.guild.get_member(discord_id)
        name = member.display_name if member else "Tu"

        await thread.send(
            f"⚠️ {name} n'a pas encore posé d'objectifs cette semaine. "
            f"Ajoutables à tout moment, pris en compte dès que postés."
        )
        if missed >= 2:
            await thread.send(
                "Deux semaines sans objectifs postés — tu veux reprendre ceux, non finis, "
                "de la semaine d'avant, ou repartir sur du neuf ?",
                view=CarryOverView(discord_id, previous_week, week_start, bot),
            )


@tasks.loop(time=datetime.strptime("21:00", "%H:%M").time().replace(tzinfo=TZ))
async def daily_checkin():
    """Lundi à samedi, 21h : poste le bouton de check-in dans chaque thread perso."""
    today = now_paris().date()
    if today.weekday() == 6:  # dimanche -> pas de check-in, c'est le jour du récap
        return
    week_start = db.current_week_start(today)
    checkin_date = today.isoformat()
    day_number = today.weekday() + 1  # 1=lundi ... 6=samedi

    for discord_id in db.get_all_users():
        thread_id = db.get_thread(discord_id)
        thread = bot.get_channel(thread_id) if thread_id else None
        if not thread:
            continue
        if db.already_checked_in_today(discord_id, checkin_date):
            continue
        member = thread.guild.get_member(discord_id)
        mention = member.mention if member else ""
        await thread.send(
            f"📋 {mention} Jour {day_number}/6 — check-in du soir.",
            view=CheckinButton(discord_id, week_start, checkin_date, bot),
        )


@tasks.loop(time=datetime.strptime("18:00", "%H:%M").time().replace(tzinfo=TZ))
async def sunday_recap():
    """Dimanche 18h : récap de la semaine écoulée + proposition de nouveaux objectifs."""
    if now_paris().weekday() != 6:
        return
    today = now_paris().date()
    week_start = db.current_week_start(today - timedelta(days=1))  # semaine qui vient de se terminer (lun-sam)
    new_week_start = db.upcoming_week_start(today)
    guild = bot.get_guild(config.GUILD_ID)
    feed = bot.get_channel(config.FEED_CHANNEL_ID)

    for discord_id in db.get_all_users():
        thread_id = db.get_thread(discord_id)
        thread = bot.get_channel(thread_id) if thread_id else None
        if not thread:
            continue
        member = guild.get_member(discord_id)
        name = member.display_name if member else "Membre"

        objectives = db.get_objectives(discord_id, week_start)
        checkins = db.get_checkins_for_week(discord_id, week_start)

        embed = discord.Embed(
            title=f"📊 Récap — {name} — semaine du {week_start}",
            color=discord.Color.gold(),
        )

        if not objectives:
            freestyle = [c for c in checkins if c["objective_id"] is None]
            summary = "\n".join(f"- {c['checkin_date']} : {c['status']}" for c in freestyle) or "Aucun check-in."
            embed.add_field(name="🎯 Objectifs de la semaine", value="Non définis", inline=False)
            embed.add_field(name="Résumé freestyle", value=summary[:1024], inline=False)
        else:
            objectifs = [o for o in objectives if o["type"] == "objectif"]
            habitudes = [o for o in objectives if o["type"] == "habitude"]
            if objectifs:
                done = sum(1 for p in objectifs if p["done"])
                lines = [f"{'✅' if p['done'] else '➡️'} {p['text']}" for p in objectifs]
                embed.add_field(
                    name=f"🎯 Objectifs : {done}/{len(objectifs)} terminés",
                    value="\n".join(lines)[:1024],
                    inline=False,
                )
            for h in habitudes:
                done_count = sum(
                    1 for c in checkins if c["objective_id"] == h["id"] and c["status"] == "✅"
                )
                embed.add_field(
                    name=f"🔁 {h['text']}",
                    value=f"{done_count}/{h['target']} jours respectés",
                    inline=False,
                )

        await thread.send(embed=embed)
        if feed:
            await feed.send(embed=embed)

        await thread.send(f"🎯 Nouveaux objectifs pour la semaine du **{new_week_start}** :")
        builder = ObjectivesBuilderView(new_week_start, bot)
        await thread.send(embed=builder.build_embed(name), view=builder)


@bot.event
async def on_ready():
    db.init_db()
    guild = discord.Object(id=config.GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    if not sunday_reminder.is_running():
        sunday_reminder.start()
    if not monday_relance.is_running():
        monday_relance.start()
    if not daily_checkin.is_running():
        daily_checkin.start()
    if not sunday_recap.is_running():
        sunday_recap.start()
    log.info(f"Connecté en tant que {bot.user} — tâches planifiées démarrées.")


if __name__ == "__main__":
    bot.run(config.TOKEN)