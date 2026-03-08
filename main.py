import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
from flask import Flask
from threading import Thread

# --- サーバー維持用 ---
app = Flask('')
@app.route('/')
def home(): 
    return f"Bot is active! {datetime.datetime.now()}"

def run(): 
    app.run(host='0.0.0.0', port=10000)

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
        await self.tree.sync()
        print("✅ 全コマンドの同期が完了しました")

bot = MyBot()

# --- 💾 データ管理（リセットまで保持） ---
DB_FILE = "reservation_data.json"

def load_data():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r") as f:
                data = json.load(f)
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
    current_time = datetime.datetime.strptime("13:00", "%H:%M")
    for i in range(34):
        slots.append({"start": current_time.strftime('%H:%M'), "user": "空き", "status": 0, "uid": None})
        current_time = current_time + datetime.timedelta(minutes=25)
    return slots

# --- 📋 スケジュール確認表の生成 ---
def gen_schedule_embed(slots):
    embed = discord.Embed(title="📋 本日の進行スケジュール", color=0x2ecc71)
    
    first_half = ""
    for i in range(0, 17):
        s = slots[i]
        user_text = f"**{s['user']}**" if s['status'] == 1 else "──"
        first_half += f"`{s['start']}` {user_text}\n"
    
    second_half = ""
    for i in range(17, 34):
        s = slots[i]
        user_text = f"**{s['user']}**" if s['status'] == 1 else "──"
        second_half += f"`{s['start']}` {user_text}\n"

    embed.add_field(name="【前半 13:00〜】", value=first_half, inline=True)
    embed.add_field(name="【後半 20:05〜】", value=second_half, inline=True)
    return embed

# --- 📅 予約ボタン用Embedの生成 ---
def gen_main_embed(slots, is_second):
    title = "📅 予約ボタン (後半)" if is_second else "📅 予約ボタン (前半)"
    embed = discord.Embed(title=title, color=0x9b59b6 if is_second else 0x3498db)
    idx = range(17, 34) if is_second else range(0, 17)
    
    lines = []
    for i in idx:
        s = slots[i]
        status_text = "[予約済]" if s["status"] == 1 else ("[不　可]" if s["status"] == 2 else "[空　き]")
        lines.append(f"{status_text} {s['start']} | {s['user'][:10]}")
    
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    return embed

# --- ボタン処理 ---
class ReserveButton(discord.ui.Button):
    def __init__(self, gid, index, label, row, schedule_msg_id):
        super().__init__(label=label, custom_id=f"btn_{gid}_{index}", row=row)
        self.gid = gid
        self.index = index
        self.schedule_msg_id = schedule_msg_id

    async def callback(self, interaction: discord.Interaction):
        db = load_data()
        if self.gid not in db: db[self.gid] = get_slots()
        data = db[self.gid][self.index]
        user = interaction.user
        is_admin = user.guild_permissions.administrator

        if data["status"] == 1 and data["uid"] != user.id and not is_admin:
            return await interaction.response.send_message("❌ 他人の予約は変更不可！", ephemeral=True)

        if is_admin: data["status"] = (data["status"] + 1) % 3
        else: data["status"] = 1 if data["status"] == 0 else 0
        data["user"] = user.display_name if data["status"] == 1 else ("不可" if data["status"] == 2 else "空き")
        data["uid"] = user.id if data["status"] == 1 else None
        
        save_data(db)

        is_second = self.index >= 17
        await interaction.response.edit_message(
            embed=gen_main_embed(db[self.gid], is_second),
            view=gen_view(self.gid, db[self.gid], is_second, self.schedule_msg_id)
        )

        if self.schedule_msg_id:
            try:
                sched_msg = await interaction.channel.fetch_message(self.schedule_msg_id)
                await sched_msg.edit(embed=gen_schedule_embed(db[self.gid]))
            except: pass

def gen_view(gid, slots, is_second, schedule_msg_id):
    view = discord.ui.View(timeout=None)
    idx = range(17, 34) if is_second else range(0, 17)
    for i in idx:
        d = slots[i]
        row = (i % 17) // 4 
        btn = ReserveButton(gid, i, d["start"], row, schedule_msg_id)
        btn.style = discord.ButtonStyle.danger if d["status"] == 1 else (discord.ButtonStyle.secondary if d["status"] == 2 else discord.ButtonStyle.primary)
        view.add_item(btn)
    return view

# --- 🚀 コマンド (データ保持版) ---
@bot.tree.command(name="全時間", description="最新の予約状況を引き継いでパネルを表示します")
async def setup_slash(interaction: discord.Interaction):
    db = load_data()
    gid = interaction.guild_id
    
    # 【ここが修正ポイント！】
    # すでにデータがある場合は、作り直さずにそのまま使う
    if gid not in db:
        db[gid] = get_slots()
        save_data(db)

    await interaction.response.send_message("📢 予約システム（データ保持モード）を起動しました。", ephemeral=True)
    
    sched_msg = await interaction.channel.send(embed=gen_schedule_embed(db[gid]))
    await interaction.channel.send(embed=gen_main_embed(db[gid], False), view=gen_view(gid, db[gid], False, sched_msg.id))
    await interaction.channel.send(embed=gen_main_embed(db[gid], True), view=gen_view(gid, db[gid], True, sched_msg.id))

@bot.tree.command(name="リセット", description="【管理者専用】すべてのデータを消去して白紙に戻します")
@app_commands.checks.has_permissions(administrator=True)
async def reset_slash(interaction: discord.Interaction):
    db = load_data()
    db[interaction.guild_id] = get_slots() # ここで初めて白紙にする
    save_data(db)
    await interaction.response.send_message("♻️ **全データをリセットしたで！新しい募集を始めてな。**")

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv('DISCORD_TOKEN')
    if TOKEN: bot.run(TOKEN)
