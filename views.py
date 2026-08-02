import discord

import database as db
import config


def build_objectives_embed(discord_id: int, week_start: str, member_name: str):
    """Embed final (lu depuis la DB) — utilisé une fois les objectifs validés."""
    objs = db.get_objectives(discord_id, week_start)
    embed = discord.Embed(
        title=f"🎯 Objectifs — semaine du {week_start}",
        description=f"**{member_name}**",
        color=discord.Color.blurple(),
    )
    if not objs:
        embed.add_field(name="Objectifs", value="Non définis", inline=False)
        return embed
    for o in objs:
        if o["type"] == "objectif":
            embed.add_field(name="🎯 Objectif", value=o["text"], inline=False)
        else:
            embed.add_field(name=f"🔁 Habitude · objectif {o['target']}x/semaine", value=o["text"], inline=False)
    return embed


class ObjectifModal(discord.ui.Modal, title="🎯 Ajouter un objectif"):
    """Un objectif = un livrable one-shot. Un seul champ, pas de syntaxe à retenir."""

    nom = discord.ui.TextInput(
        label="Nom du objectif",
        style=discord.TextStyle.short,
        placeholder="Ex : Finir la maquette Figma",
        max_length=200,
        required=True,
    )

    def __init__(self, builder_view: "ObjectivesBuilderView"):
        super().__init__()
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction):
        self.builder_view.pending.append({
            "type": "objectif",
            "text": self.nom.value.strip(),
            "target": None,
        })
        self.builder_view.refresh_buttons()
        embed = self.builder_view.build_embed(interaction.user.display_name)
        await interaction.response.edit_message(embed=embed, view=self.builder_view)


class HabitudeModal(discord.ui.Modal, title="🔁 Ajouter une habitude"):
    """Une habitude = récurrente. Le rythme est un champ séparé, pas de parenthèses à écrire."""

    nom = discord.ui.TextInput(
        label="Nom de l'habitude",
        style=discord.TextStyle.short,
        placeholder="Ex : Sport, Lecture, Pas d'écran après 22h",
        max_length=200,
        required=True,
    )
    frequence = discord.ui.TextInput(
        label="Combien de fois par semaine ? (1 à 6)",
        style=discord.TextStyle.short,
        placeholder="3",
        max_length=1,
        required=True,
    )

    def __init__(self, builder_view: "ObjectivesBuilderView"):
        super().__init__()
        self.builder_view = builder_view

    async def on_submit(self, interaction: discord.Interaction):
        raw = self.frequence.value.strip()
        target = int(raw) if raw.isdigit() else 6
        target = max(1, min(6, target))  # les check-ins ne courent que lundi -> samedi

        self.builder_view.pending.append({
            "type": "habitude",
            "text": self.nom.value.strip(),
            "target": target,
        })
        self.builder_view.refresh_buttons()
        embed = self.builder_view.build_embed(interaction.user.display_name)
        await interaction.response.edit_message(embed=embed, view=self.builder_view)


class ObjectivesBuilderView(discord.ui.View):
    """
    Formulaire guidé pour poser les objectifs de la semaine.
    Remplace l'ancien système en texte libre : chaque objectif est ajouté
    un par un via un petit formulaire dédié (objectif OU habitude), donc
    aucune syntaxe à retenir ni emoji à taper à la main.
    """

    def __init__(self, week_start: str, bot, pending=None):
        super().__init__(timeout=None)
        self.week_start = week_start
        self.bot = bot
        self.pending = pending if pending is not None else []
        self.refresh_buttons()

    def refresh_buttons(self):
        full = len(self.pending) >= config.MAX_OBJECTIVES
        self.add_objectif_btn.disabled = full
        self.add_habitude_btn.disabled = full
        self.valider_btn.disabled = len(self.pending) == 0
        self.reset_btn.disabled = len(self.pending) == 0

    def build_embed(self, member_name: str) -> discord.Embed:
        embed = discord.Embed(
            title=f"🎯 Objectifs — semaine du {self.week_start}",
            description=f"**{member_name}**",
            color=discord.Color.blurple(),
        )
        if not self.pending:
            embed.add_field(
                name="Aucun objectif ajouté pour l'instant",
                value="Clique sur un bouton ci-dessous 👇",
                inline=False,
            )
        else:
            for o in self.pending:
                if o["type"] == "objectif":
                    embed.add_field(name="🎯 Objectif", value=o["text"], inline=False)
                else:
                    embed.add_field(
                        name=f"🔁 Habitude · objectif {o['target']}x/semaine",
                        value=o["text"],
                        inline=False,
                    )
        restant = config.MAX_OBJECTIVES - len(self.pending)
        if restant > 0:
            embed.set_footer(text=f"{restant} emplacement(s) restant(s) sur {config.MAX_OBJECTIVES} · clique sur Valider quand tu as fini")
        else:
            embed.set_footer(text="Maximum atteint — clique sur Valider pour enregistrer")
        return embed

    @discord.ui.button(label="Ajouter un objectif", style=discord.ButtonStyle.primary, emoji="🎯", row=0)
    async def add_objectif_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ObjectifModal(self))

    @discord.ui.button(label="Ajouter une habitude", style=discord.ButtonStyle.secondary, emoji="🔁", row=0)
    async def add_habitude_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(HabitudeModal(self))

    @discord.ui.button(label="Valider mes objectifs", style=discord.ButtonStyle.success, emoji="✅", row=1, disabled=True)
    async def valider_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        discord_id = interaction.user.id
        db.ensure_user(discord_id)
        db.clear_objectives(discord_id, self.week_start)
        for o in self.pending:
            db.add_objective(discord_id, self.week_start, o["type"], o["text"], o["target"])
        db.reset_missed(discord_id)

        embed = build_objectives_embed(discord_id, self.week_start, interaction.user.display_name)
        embed.set_footer(text="✅ Objectifs enregistrés pour la semaine")
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(embed=embed, view=self)

        feed = self.bot.get_channel(config.FEED_CHANNEL_ID)
        if feed:
            await feed.send(embed=embed)

    @discord.ui.button(label="Recommencer", style=discord.ButtonStyle.danger, emoji="🗑️", row=1, disabled=True)
    async def reset_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.pending = []
        self.refresh_buttons()
        embed = self.build_embed(interaction.user.display_name)
        await interaction.response.edit_message(embed=embed, view=self)


class CarryOverView(discord.ui.View):
    """Proposé après 2 semaines d'affilée sans objectifs postés."""

    def __init__(self, discord_id: int, previous_week: str, new_week: str, bot):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.previous_week = previous_week
        self.new_week = new_week
        self.bot = bot

    @discord.ui.button(label="Reprendre les objectifs non finis", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def carry_over(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message("Ce bouton n'est pas pour toi 🙂", ephemeral=True)
            return
        old = db.get_objectives(self.discord_id, self.previous_week)
        unfinished = [o for o in old if not (o["type"] == "objectif" and o["done"])]
        if not unfinished:
            await interaction.response.send_message("Aucun objectif à reprendre, tout était fini ✅", ephemeral=True)
            return
        db.clear_objectives(self.discord_id, self.new_week)
        for o in unfinished:
            db.add_objective(self.discord_id, self.new_week, o["type"], o["text"], o["target"])
        db.reset_missed(self.discord_id)
        embed = build_objectives_embed(self.discord_id, self.new_week, interaction.user.display_name)
        await interaction.response.send_message(
            content="✅ Objectifs de la semaine dernière repris.", embed=embed
        )
        feed = self.bot.get_channel(config.FEED_CHANNEL_ID)
        if feed:
            await feed.send(embed=embed)

    @discord.ui.button(label="Poser de nouveaux objectifs", style=discord.ButtonStyle.primary, emoji="🎯")
    async def new_objectives(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message("Ce bouton n'est pas pour toi 🙂", ephemeral=True)
            return
        builder = ObjectivesBuilderView(self.new_week, self.bot)
        await interaction.response.send_message(
            embed=builder.build_embed(interaction.user.display_name), view=builder
        )


class CheckinModal(discord.ui.Modal, title="Check-in du soir"):
    """Construit dynamiquement 1 champ par objectif (max 4) + 1 champ motivation."""

    def __init__(self, discord_id: int, week_start: str, checkin_date: str, objectives, bot):
        super().__init__()
        self.discord_id = discord_id
        self.week_start = week_start
        self.checkin_date = checkin_date
        self.objectives = objectives
        self.bot = bot
        self.inputs = {}

        for o in objectives:
            if o["type"] == "habitude":
                label = f"🔁 {o['text'][:35]} (oui/non)"
                placeholder = "oui / non"
            else:
                label = f"🎯 {o['text'][:35]}"
                placeholder = "terminé / en cours / pas touché"
            field = discord.ui.TextInput(
                label=label[:45],
                style=discord.TextStyle.short,
                placeholder=placeholder,
                required=True,
                max_length=100,
            )
            self.add_item(field)
            self.inputs[o["id"]] = field

        self.motivation = discord.ui.TextInput(
            label="Motivation (1-10)",
            style=discord.TextStyle.short,
            placeholder="8",
            required=True,
            max_length=2,
        )
        self.add_item(self.motivation)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            motivation_value = int(self.motivation.value.strip())
        except ValueError:
            motivation_value = None

        lines = []
        for obj_id, field in self.inputs.items():
            obj = next(o for o in self.objectives if o["id"] == obj_id)
            value = field.value.strip().lower()
            if obj["type"] == "habitude":
                status = "✅" if value in ("oui", "yes", "y", "o", "✅") else "❌"
                db.add_checkin(self.discord_id, self.checkin_date, obj_id, status, motivation_value)
                lines.append(f"🔁 {obj['text']} : {status}")
            else:
                done = "termin" in value
                if done:
                    db.mark_objective_done(obj_id, True)
                db.add_checkin(self.discord_id, self.checkin_date, obj_id, field.value.strip(), motivation_value)
                mark = "✅" if done else "➡️"
                lines.append(f"🎯 {obj['text']} : {field.value.strip()} {mark}")

        embed = discord.Embed(
            title=f"📋 Check-in — {interaction.user.display_name}",
            description="\n".join(lines) + f"\n\n🔥 Motivation : {motivation_value}/10",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)
        feed = self.bot.get_channel(config.FEED_CHANNEL_ID)
        if feed:
            await feed.send(embed=embed)


class FreestyleCheckinModal(discord.ui.Modal, title="Check-in du soir (freestyle)"):
    update = discord.ui.TextInput(
        label="Sur quoi as-tu avancé aujourd'hui ?",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True,
    )

    def __init__(self, discord_id: int, checkin_date: str, bot):
        super().__init__()
        self.discord_id = discord_id
        self.checkin_date = checkin_date
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction):
        db.add_checkin(self.discord_id, self.checkin_date, None, self.update.value.strip(), None)
        embed = discord.Embed(
            title=f"📋 Check-in freestyle — {interaction.user.display_name}",
            description=self.update.value.strip(),
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed)
        feed = self.bot.get_channel(config.FEED_CHANNEL_ID)
        if feed:
            await feed.send(embed=embed)


class CheckinButton(discord.ui.View):
    def __init__(self, discord_id: int, week_start: str, checkin_date: str, bot):
        super().__init__(timeout=None)
        self.discord_id = discord_id
        self.week_start = week_start
        self.checkin_date = checkin_date
        self.bot = bot

    @discord.ui.button(label="Faire mon check-in", style=discord.ButtonStyle.success, emoji="📋")
    async def do_checkin(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.discord_id:
            await interaction.response.send_message("Ce check-in n'est pas pour toi 🙂", ephemeral=True)
            return
        if db.already_checked_in_today(self.discord_id, self.checkin_date):
            await interaction.response.send_message("Tu as déjà fait ton check-in aujourd'hui ✅", ephemeral=True)
            return

        objectives = db.get_objectives(self.discord_id, self.week_start)
        if objectives:
            await interaction.response.send_modal(
                CheckinModal(self.discord_id, self.week_start, self.checkin_date, objectives, self.bot)
            )
        else:
            await interaction.response.send_modal(
                FreestyleCheckinModal(self.discord_id, self.checkin_date, self.bot)
            )