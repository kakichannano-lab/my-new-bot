import discord
from discord import app_commands
from discord.ext import commands
import datetime
import os
import json
from flask import Flask
from threading import Thread

# --- サーバー維持用 (cron-jobエラー対策: 返信を最短に) ---
app = Flask('')
@app.route('/')
def home(): 
    return "ok", 200 

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

# --- 💾 データ管理 ---
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

# --- 📅 予約パネル用Embed生成 ---
def gen_main_embed(slots, is_second):
    booked_count = sum(1 for s in slots if s["status"] == 1)
    title = f"📅 予約パネル ({'後半' if is_second else '前半'}) [{booked_count}/34枠埋]"
    embed = discord.Embed(title=title, color=0x9b59b6 if is_second else 0x3498db)
    idx = range(17, 34) if is_second else range(0, 17)
    
    lines = []
    for i in idx:
        s = slots[i]
        status_text = "[予約済]" if s["status"] == 1 else ("[不　可]" if s["status"] == 2 else "[空　き]")
        lines.append(f"{status_text} {s['start']} | {s['user'][:10]}")
    
    embed.description = "```\n" + "\n".join(lines) + "\n```"
    return embed

# --- 🔘 ボタン処理 ---
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
        # 鯖主判定（サーバーの所有者かどうか）のみ！
        is_owner = interaction.guild.owner_id == user.id

        # --- 権限チェック ---
        if not is_owner:
            # 一般ユーザーは「不可」枠は触れない
            if data["status"] == 2:
                return await interaction.response.send_message("❌ この枠は現在使用不可やで。", ephemeral=True)
            # 一般ユーザーは他人の予約は触れない
            if data["status"] == 1 and data["uid"] != user.id:
                return await interaction.response.send_message("❌ 他人の予約は変更できへんで。", ephemeral=True)

        # --- ステータス更新 ---
        if is_owner:
            data["status"] = (data["status"] + 1) % 3 # 空→予約→不可→空
        else:
            data["status"] = 1 if data["status"] == 0 else 0 # 空<->予約
        
        data["user"] = user.display_name if data["status"] == 1 else ("不可" if data["status"] == 2 else "空き")
        data["uid"] = user.id if data["status"] != 0 else None
        
        save_data(db)
        is_second = self.index >= 17
        await interaction.response.edit_message(embed=gen_main_embed(db[self.gid], is_second), view=gen_view(self.gid, db[self.gid], is_second))

def gen_view(gid, slots, is_second):
    view = discord.ui.View(timeout=None)
    idx = range(17, 34) if is_second else range(0, 17)
    for i in idx:
        d = slots[i]
        row = (i % 17) // 4 
        btn = ReserveButton(gid, i, d["start"], row)
        btn.style = discord.ButtonStyle.danger if d["status"] == 1 else (discord.ButtonStyle.secondary if d["status"] == 2 else discord.ButtonStyle.primary)
        view.add_item(btn)
    return view

# --- 🚀 コマンド群 ---
@bot.tree.command(name="予約", description="時刻指定予約（例: 13:00）")
async def reserve_slash(interaction: discord.Interaction, 時刻: str):
    db = load_data(); gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots()
    slot = next((s for s in db[gid] if s["start"] == 時刻), None)
    if not slot: return await interaction.response.send_message("❌ 時刻が正しくないで。", ephemeral=True)
    
    user = interaction.user
    is_owner = interaction.guild.owner_id == user.id
    if not is_owner and slot["status"] != 0 and slot["uid"] != user.id:
        return await interaction.response.send_message("❌ 予約済みの枠やで。", ephemeral=True)
        
    slot["status"], slot["user"], slot["uid"] = 1, user.display_name, user.id
    save_data(db)
    await interaction.response.send_message(f"✅ {時刻} を予約したで！", ephemeral=False)

@bot.tree.command(name="全時間")
async def all_slash(interaction: discord.Interaction):
    db = load_data(); gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message("📢 表示中...", ephemeral=True)
    await interaction.channel.send(embed=gen_main_embed(db[gid], False), view=gen_view(gid, db[gid], False))
    await interaction.channel.send(embed=gen_main_embed(db[gid], True), view=gen_view(gid, db[gid], True))

@bot.tree.command(name="リセット")
async def reset_slash(interaction: discord.Interaction):
    db = load_data(); db[interaction.guild_id] = get_slots(); save_data(db)
    await interaction.response.send_message("♻️ **リセット完了！**")

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv('DISCORD_TOKEN')
    if TOKEN: bot.run(TOKEN)
