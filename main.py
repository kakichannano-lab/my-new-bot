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

# --- データ保存の仕組み ---
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
    for i in range(34): # 13:00から25分刻みで34枠
        slots.append({
            "start": current_time.strftime('%H:%M'), 
            "user": "空き", 
            "status": 0, 
            "uid": None
        })
        current_time = current_time + datetime.timedelta(minutes=25)
    return slots

# --- 表示とボタンのロジック ---
def format_line(slot):
    status = slot["status"]
    # 常にステータスを表示（終了判定なし）
    text = "[予約済]" if status == 1 else ("[不　可]" if status == 2 else "[空　き]")
    return f"{text} {slot['start']} | {slot['user'][:10]}"

def gen_embed(slots, is_second):
    title = "📅 予約リスト (後半 20:05〜)" if is_second else "📅 予約リスト (前半 13:00〜)"
    embed = discord.Embed(title=title, color=0x9b59b6 if is_second else 0x3498db)
    idx = range(17, 34) if is_second else range(0, 17)
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
        
        # 予約済みの枠を本人が押すか、管理者が押した場合は解除/変更
        if data["status"] == 1 and data["uid"] != user.id and not is_admin:
            return await interaction.response.send_message("❌ 他人の予約は変更できへんで", ephemeral=True)
        
        if is_admin: 
            # 管理者は 空き -> 予約済 -> 不可 のループ
            data["status"] = (data["status"] + 1) % 3
        else: 
            # 一般ユーザーは 空き <-> 予約済 の切り替え
            data["status"] = 1 if data["status"] == 0 else 0
        
        data["user"] = user.display_name if data["status"] == 1 else ("不可" if data["status"] == 2 else "空き")
        data["uid"] = user.id if data["status"] == 1 else None
        
        save_data(db)
        is_second = self.index >= 17
        await interaction.response.edit_message(
            embed=gen_embed(db[self.gid], is_second), 
            view=gen_view(self.gid, db[self.gid], is_second)
        )

def gen_view(gid, slots, is_second):
    view = discord.ui.View(timeout=None)
    idx = range(17, 34) if is_second else range(0, 17)
    for i in idx:
        d = slots[i]
        row = (i % 17) // 4 
        btn = ReserveButton(gid, i, d["start"], row)
        
        # 色の設定
        if d["status"] == 1:
            btn.style = discord.ButtonStyle.danger  # 赤（予約済）
        elif d["status"] == 2:
            btn.style = discord.ButtonStyle.secondary # 灰（不可）
        else:
            btn.style = discord.ButtonStyle.primary   # 青（空き）
            
        view.add_item(btn)
    return view

# --- スラッシュコマンド群 ---
@bot.tree.command(name="全時間", description="13:00〜03:00の管理表を表示します")
async def setup_slash(interaction: discord.Interaction):
    db = load_data(); gid = interaction.guild_id; db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message("📢 予約管理表（全時間）を作成したで！", ephemeral=False)
    await interaction.channel.send(embed=gen_embed(db[gid], False), view=gen_view(gid, db[gid], False))
    await interaction.channel.send(embed=gen_embed(db[gid], True), view=gen_view(gid, db[gid], True))

@bot.tree.command(name="前半", description="前半 (13:00〜19:40) を表示します")
async def front_slash(interaction: discord.Interaction):
    db = load_data(); gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message(embed=gen_embed(db[gid], False), view=gen_view(gid, db[gid], False))

@bot.tree.command(name="後半", description="後半 (20:05〜02:45) を表示します")
async def back_slash(interaction: discord.Interaction):
    db = load_data(); gid = interaction.guild_id
    if gid not in db: db[gid] = get_slots(); save_data(db)
    await interaction.response.send_message(embed=gen_embed(db[gid], True), view=gen_view(gid, db[gid], True))

@bot.tree.command(name="リセット", description="すべての予約を白紙に戻します")
async def reset_slash(interaction: discord.Interaction):
    db = load_data(); db[interaction.guild_id] = get_slots(); save_data(db)
    await interaction.response.send_message("♻️ **予約リストをリセットしたで！**")

if __name__ == "__main__":
    keep_alive()
    TOKEN = os.getenv('DISCORD_TOKEN')
    if TOKEN: bot.run(TOKEN)
