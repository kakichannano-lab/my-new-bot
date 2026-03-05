import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
import time
from flask import Flask
from threading import Thread

# --- サーバー維持用 (Renderの寝落ち防止) ---
app = Flask('')

@app.route('/')
def home(): 
    return f"Bot is active! {datetime.datetime.now()}"

def run(): 
    app.run(host='0.0.0.0', port=10000) # Renderのデフォルトポートに変更

def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()

# --- Bot本体の設定 ---
class MyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        # スラッシュコマンドをDiscordに登録
        await self.tree.sync()
        print("✅ スラッシュコマンドを同期しました")

bot = MyBot()

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    print('Bot is ready!')

# --- データ保存の仕組み ---
DB_FILE = "server_data.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                content = f.read()
                if not content.strip(): return {}
                data = json.loads(content)
                return {int(k): v for k, v in data.items()}
        except: return {}
    return {}

def save_data(data_to_save):
    try:
        with open(DB_FILE, "w") as f:
            json.dump(data_to_save, f, indent=4)
    except: pass

def get_slots():
    slots = []
    start = datetime.datetime.strptime("13:00", "%H:%M")
    for i in range(30): 
        slots.append({"start": start.strftime('%H:%M'), "user": "空き", "status": 0, "uid": None})
        start = start + datetime.timedelta(minutes=30)
    return slots

# --- 管理者用隠しコマンド (!sync) ---
@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    await bot.tree.sync()
    await ctx.send("✅ スラッシュコマンドを最新の状態に更新しました！")

# --- スラッシュコマンド群 ---
@bot.tree.command(name="全時間", description="【全時間帯】の管理表を表示します")
async def setup_slash(interaction: discord.Interaction):
    db = load_data()
    gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    data = db[gid]
    await interaction.response.send_message(f"📢 {interaction.user.display_name}が管理表を呼び出しました。", ephemeral=False)
    await interaction.channel.send(embed=gen_embed(data, False), view=gen_view(gid, data, False))
    await interaction.channel.send(embed=gen_embed(data, True), view=gen_view(gid, data, True))

@bot.tree.command(name="前半", description="【前半 (13:00〜)】のみ表示します")
async def front_slash(interaction: discord.Interaction):
    db = load_data()
    gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message(embed=gen_embed(db[gid], False), view=gen_view(gid, db[gid], False))

@bot.tree.command(name="後半", description="【後半 (20:30〜)】のみ表示します")
async def back_slash(interaction: discord.Interaction):
    db = load_data()
    gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message(embed=gen_embed(db[gid], True), view=gen_view(gid, db[gid], True))

@bot.tree.command(name="リセット", description="【内容リセット】誰でも予約をすべて空きに戻せます")
async def reset_slash(interaction: discord.Interaction):
    db = load_data()
    db[interaction.guild_id] = get_slots()
    save_data(db)
    await interaction.response.send_message(f"♻️ **{interaction.user.display_name}により予約リストがリセットされました。**")

# --- 表示とボタンのロジック ---
def format_line(slot):
    status = slot["status"]
    text = "[予約済]" if status == 1 else ("[不　可]" if status == 2 else "[空　き]")
    return f"{text} {slot['start']} | {slot['user'][:10]}"

def gen_embed(slots, is_second):
    title = "📅 予約リスト(後半)" if is_second else "📅 予約リスト(前半)"
    embed = discord.Embed(title=title, color=0x2b2d31)
    idx = range(15, 30) if is_second else range(0, 15)
    lines = [format_line(slots[i]) for i in idx]
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    return embed

class ReserveButton(discord.ui.Button):
    def __init__(self, gid, index, label, row):
        super().__init__(label=label, custom_id=f"btn_{gid}_{index}", row=row)
        self.gid = gid
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        db = load_data()
        if self.gid not in db: db[self.gid] = get_slots()
        data = db[self.gid][self.index]
        user = interaction.user
        is_admin = user.guild_permissions.administrator
        if data["status"] == 1 and data["uid"] != user.id and not is_admin:
            return await interaction.response.send_message("❌ 他人の予約は変更できません", ephemeral=True)
        if is_admin: 
            data["status"] = (data["status"] + 1) % 3
        else: 
            data["status"] = 1 if data["status"] == 0 else 0
        data["user"] = user.display_name if data["status"] == 1 else ("不可" if data["status"] == 2 else "空き")
        data["uid"] = user.id if data["status"] == 1 else None
        save_data(db)
        is_second = self.index >= 15
        await interaction.response.edit_message(embed=gen_embed(db[self.gid], is_second), view=gen_view(self.gid, db[self.gid], is_second))

def gen_view(gid, slots, is_second):
    view = discord.ui.View(timeout=None)
    idx = range(15, 30) if is_second else range(0, 15)
    for i in idx:
        d = slots[i]
        btn = ReserveButton(gid, i, d["start"], (i % 15) // 3)
        btn.style = discord.ButtonStyle.danger if d["status"] == 1 else (discord.ButtonStyle.secondary if d["status"] == 2 else discord.ButtonStyle.primary)
        view.add_item(btn)
    return view

# --- 実行 ---
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ DISCORD_TOKENがEnvironment Variablesに設定されていません！")
