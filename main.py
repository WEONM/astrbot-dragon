# main.py
# 龙族轮盘：以《龙族》言灵世界观重写的 AstrBot 恶魔轮盘插件
# v1.10.0：新增屠龙模式（单人 PvE 挑战四大龙王，Boss AI 自动回合/入场费/击杀奖励/解锁机制）；
#          信息类言灵（风王之瞳/先知/神谕/阴流）改为私发告知，避免群聊信息泄漏
# v1.9.0：新增 7 种言灵（湮灭/怒焰/蜕生/血鳞/黄金瞳/血脉诅咒/轮回），
#         引入复活/吸血/禁抽/伤害强化/生命互换新机制，言灵总数 43 → 50
# v1.8.0：新增龙币积分与押注系统（胜负奖励/连胜加成/排行榜/对局下注，跨重启持久化）
# v1.7.0：修复抽卡血量显示 / 言灵复制返还 / 言灵致死时 await 崩溃；
#         统一伤害结算；新增认输/丢弃指令；对局无操作超时自动结束；可选跨重启持久化。
from astrbot.api.all import *  # 导入 AstrBot 所有 API
import asyncio
import json
import os
import random
import textwrap
import time
from types import SimpleNamespace

# ---------------- 常量 ----------------
BULLET_LIVE = "实弹"            # 内部类型：龙炎弹
BULLET_BLANK = "空包弹"         # 内部类型：空包弹
BULLET_LIVE_DISPLAY = "龙炎弹"
BULLET_BLANK_DISPLAY = "空包弹"

RARITY_COMMON = "普通"
RARITY_RARE = "稀有"
RARITY_LEGEND = "传说"
RARITY_ICONS = {RARITY_COMMON: "◆", RARITY_RARE: "★★", RARITY_LEGEND: "★★★"}

STATUS_WAITING = "waiting"
STATUS_FULL = "full"
STATUS_STARTED = "started"

ITEM_CAP = 8               # 言灵背包上限
DRAW_BASE_COST = 2         # 首抽消耗生命
DRAW_COST_MULTIPLIER = 2   # 后续每次抽卡消耗翻倍
PVP_MAX_ITEMS_PER_ROUND = 3  # PvP 每轮每人最多使用言灵次数
TEAM_MAX_SIZE = 3          # 组队讨伐最多人数
TEAM_BOSS_HP_PER_EXTRA = 4 # 每多一名队员，Boss 额外生命
WATCHDOG_INTERVAL = 60     # 守护任务扫描间隔（秒）
STATE_FILE_NAME = "game_state.json"
ECO_FILE_NAME = "economy.json"   # 龙币/战绩数据（始终持久化）

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME_DIR = os.path.basename(PLUGIN_DIR)
RES_DIR = os.path.join(PLUGIN_DIR, "res")
# AstrBot 约定：运行数据放 data/plugin_data/<插件包名>/，升级插件不会被覆盖
PLUGIN_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(PLUGIN_DIR)), "plugin_data", PLUGIN_NAME_DIR
)
STATE_FILE = os.path.join(PLUGIN_DATA_DIR, STATE_FILE_NAME)
ECO_FILE = os.path.join(PLUGIN_DATA_DIR, ECO_FILE_NAME)

# ---------------- 屠龙模式 Boss ----------------
BOSS_ORDER = ["诺顿", "芬里厄", "伊邪那美", "尼德霍格"]
BOSSES = {
    "诺顿": {
        "title": "青铜与火之王", "name": "青铜与火之王·诺顿", "hp": 10,
        "skills": ["言灵·君焰", "言灵·烛龙", "言灵·审判"],
        "desc": "掌控青铜与火焰的君王，炼金术的巅峰造物。",
    },
    "芬里厄": {
        "title": "大地与山之王", "name": "大地与山之王·芬里厄", "hp": 14,
        "skills": ["言灵·青铜御座", "言灵·无尘之地", "言灵·冬"],
        "desc": "山岳般的巨兽，大地为甲，岩石为盾。",
    },
    "伊邪那美": {
        "title": "白王", "name": "白王·伊邪那美", "hp": 12,
        "skills": ["言灵·神谕", "言灵·冬", "言灵·归墟"],
        "desc": "黄泉之国的女王，命运在她眼中如掌纹般清晰。",
    },
    "尼德霍格": {
        "title": "黑龙王", "name": "黑龙王·尼德霍格", "hp": 16,
        "skills": ["言灵·皇帝", "言灵·时间零", "言灵·湿婆业舞"],
        "desc": "啃噬世界树根须的黑龙王，诸神黄昏的引路人。",
    },
}

def res_path(name: str) -> str:
    return os.path.join(RES_DIR, name)

def generate_random_bullet_list(min_count: int = 3, max_count: int = 8):
    """
    随机生成一个弹夹列表：
      - 子弹数量在 min_count ~ max_count 之间
      - 每发子弹为 "实弹" 或 "空包弹"（各50%概率）
      - 最后洗牌后返回
    """
    bullet_count = random.randint(min_count, max_count)
    bullets = []
    for _ in range(bullet_count):
        bullets.append(BULLET_LIVE if random.random() < 0.5 else BULLET_BLANK)
    random.shuffle(bullets)
    return bullets

def display_bullet(bullet: str) -> str:
    """把内部子弹类型转换为龙族风格的显示名。"""
    return BULLET_LIVE_DISPLAY if bullet == BULLET_LIVE else BULLET_BLANK_DISPLAY

def other_player(player_key: str) -> str:
    """返回对局中另一名玩家的 key。"""
    return "player2" if player_key == "player1" else "player1"

@register(
    "龙族轮盘",         # 插件唯一识别名（显示为“龙族轮盘”）
    "衔红花的鸟",       # 作者
    "龙族轮盘",          # 简短描述
    "1.10.0"            # 版本号
)
class DragonRoulette(Star):
    """
    以《龙族》为底层世界观的恶魔轮盘插件。
    卡塞尔学院地下赌局，混血种们以言灵代替道具互相博弈。
    言灵·镜瞳可以复制对方的言灵，言灵·皇帝则是隐藏彩蛋。
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        if not config:
            config = {}
        self.config = {
            "admin": config.get("admin", []),               # 管理员列表（ID列表）
            "maxWaitTime": config.get("maxWaitTime", 180),  # 等待玩家2加入的最大秒数
            "gameTimeout": config.get("gameTimeout", 60),   # 对局无操作超时自动结束（分钟，0=关闭）
            "persistGames": config.get("persistGames", False),  # 是否跨重启保存对局
            "startCoins": config.get("startCoins", 100),    # 新玩家初始龙币
            "winReward": config.get("winReward", 30),       # 胜场奖励龙币
            "loseReward": config.get("loseReward", 10),     # 参与安慰龙币
            "streakBonus": config.get("streakBonus", 5),
            "dragonFee": config.get("dragonFee", 20),                    # 屠龙入场费
            "dragonRewards": config.get("dragonRewards", [50, 80, 100, 150]),  # 各 Boss 击杀奖励    # 每级连胜加成龙币（最多 5 级）
        }
        self.games = {}  # 存储各群/会话的游戏数据
        self.economy = {}  # 龙币/战绩（uid -> 档案），始终持久化
        self._watchdog_task = None

        # 言灵图鉴：全部采用《龙族》原著/官方设定中出现过的言灵名称
        # category: 攻击 / 防御 / 辅助 / 特殊
        # rarity: 普通 / 稀有 / 传说
        self.item_list = {
            # ===== 攻击系 =====
            "言灵·君焰": {
                "category": "攻击", "rarity": "稀有",
                "chant": "燃烧吧，烧尽吾敌——君焰！",
                "description": "下一发造成双倍伤害，不可叠加",
                "use": self.use_junyan,
            },
            "言灵·雷池": {
                "category": "攻击", "rarity": "稀有",
                "chant": "雷霆万钧，落于雷池——雷池！",
                "description": "对对手造成1点伤害，并随机丢弃对方一个言灵",
                "use": self.use_leichi,
            },
            "言灵·审判": {
                "category": "攻击", "rarity": "传说",
                "chant": "罪与罚，皆由我判——审判！",
                "description": "对方下一次龙血冲击强制指向自己，且你下一发龙炎弹伤害翻倍",
                "use": self.use_shenpan,
            },
            "言灵·烛龙": {
                "category": "攻击", "rarity": "传说",
                "chant": "烛龙睁眼，昼夜逆转——烛龙！",
                "description": "下一发子弹必定变为龙炎弹，且造成双倍伤害",
                "use": self.use_zhulong,
            },
            "言灵·黑炎牢狱": {
                "category": "攻击", "rarity": "稀有",
                "chant": "黑炎为牢，灼魂焚骨——黑炎牢狱！",
                "description": "对对方造成1点伤害，并附加炽日压制",
                "use": self.use_heiyanlaoyu,
            },
            "言灵·苍雷支配": {
                "category": "攻击", "rarity": "传说",
                "chant": "苍雷所至，万物臣服——苍雷支配！",
                "description": "对对手造成3点伤害（若对方有护盾则抵消）",
                "use": self.use_cangleizhipei,
            },
            "言灵·深血": {
                "category": "攻击", "rarity": "普通",
                "chant": "深血浸骨，毒噬心脉——深血！",
                "description": "对对手造成1点伤害",
                "use": self.use_shenxue,
            },
            "言灵·炽日": {
                "category": "攻击", "rarity": "普通",
                "chant": "炽日凌空，目盲神摇——炽日！",
                "description": "令对方下一次龙血冲击伤害减半（至少减伤1）",
                "use": self.use_chiri,
            },
            # ===== 防御系 =====
            "言灵·无尘之地": {
                "category": "防御", "rarity": "稀有",
                "chant": "尘埃落定，万法不侵——无尘之地！",
                "description": "卸下当前膛内的子弹",
                "use": self.use_wuchen,
            },
            "言灵·圣裁": {
                "category": "防御", "rarity": "普通",
                "chant": "以圣光裁断伤痛——圣裁！",
                "description": "恢复1点生命值",
                "use": self.use_shengcai,
            },
            "言灵·青铜御座": {
                "category": "防御", "rarity": "稀有",
                "chant": "青铜铸就，御座降临——青铜御座！",
                "description": "获得护盾效果，下一次攻击伤害将被抵消",
                "use": self.use_qingtong,
            },
            "言灵·不朽": {
                "category": "防御", "rarity": "传说",
                "chant": "吾身不朽，万古不灭——不朽！",
                "description": "恢复3点生命，并清除所有负面状态",
                "use": self.use_buxiu,
            },
            "言灵·王之侍": {
                "category": "防御", "rarity": "稀有",
                "chant": "王前之侍，万军辟易——王之侍！",
                "description": "无护盾则获得护盾；已有护盾则恢复1点生命",
                "use": self.use_wangzhishi,
            },
            "言灵·鬼胜": {
                "category": "防御", "rarity": "普通",
                "chant": "鬼胜附体，痛觉皆无——鬼胜！",
                "description": "恢复2点生命，但随机丢弃一个自己的言灵",
                "use": self.use_guiisheng,
            },
            "言灵·黑日": {
                "category": "防御", "rarity": "传说",
                "chant": "黑日当空，万火归寂——黑日！",
                "description": "恢复2点生命并获得护盾",
                "use": self.use_heiri,
            },
            # ===== 辅助系 =====
            "言灵·镜瞳": {
                "category": "辅助", "rarity": "传说",
                "chant": "黄金瞳开，万象皆映——镜瞳！",
                "description": "复制对方一个随机言灵，并免费获得一个随机言灵",
                "use": self.use_jingtong,
            },
            "言灵·风王之瞳": {
                "category": "辅助", "rarity": "稀有",
                "chant": "风啊，为我睁眼——风王之瞳！",
                "description": "查看当前膛内的子弹",
                "use": self.use_fengwang,
            },
            "言灵·先知": {
                "category": "辅助", "rarity": "普通",
                "chant": "未来在我耳边低语——先知！",
                "description": "随机告知枪膛中某发子弹的类型（不移除）",
                "use": self.use_xianzhi,
            },
            "言灵·镰鼬": {
                "category": "辅助", "rarity": "稀有",
                "chant": "疾风为刃，窃取万物——镰鼬！",
                "description": "偷走对方背包中的随机一个言灵",
                "use": self.use_lianyou,
            },
            "言灵·蛇": {
                "category": "辅助", "rarity": "普通",
                "chant": "蛇瞳所视，无所遁形——蛇！",
                "description": "随机丢弃对方一个言灵",
                "use": self.use_she,
            },
            "言灵·血系结罗": {
                "category": "辅助", "rarity": "普通",
                "chant": "血网交织，因果毕现——血系结罗！",
                "description": "双方各获得一个随机言灵",
                "use": self.use_xuexijieluo,
            },
            "言灵·天演": {
                "category": "辅助", "rarity": "稀有",
                "chant": "天演万象，算尽苍生——天演！",
                "description": "免费抽取一张随机言灵（不消耗生命，不增加抽卡费用）",
                "use": self.use_tianyan,
            },
            "言灵·刹那": {
                "category": "辅助", "rarity": "稀有",
                "chant": "刹那芳华，流光逆转——刹那！",
                "description": "重置本回合抽卡费用（下次抽卡从2血开始）",
                "use": self.use_chana,
            },
            "言灵·血脉牵引": {
                "category": "辅助", "rarity": "稀有",
                "chant": "血脉为引，命运互换——血脉牵引！",
                "description": "与对方随机交换一个言灵",
                "use": self.use_xuemaiqianyin,
            },
            "言灵·神谕": {
                "category": "辅助", "rarity": "传说",
                "chant": "神谕降世，未来可见——神谕！",
                "description": "查看当前弹夹所有子弹顺序，将下一发变为空包弹，并获得一次额外行动权",
                "use": self.use_shenyu,
            },
            # ===== 特殊系 =====
            "言灵·王权": {
                "category": "特殊", "rarity": "稀有",
                "chant": "吾言即律令——王权！",
                "description": "让对方跳过下一回合",
                "use": self.use_wangquan,
            },
            "言灵·冥照": {
                "category": "特殊", "rarity": "普通",
                "chant": "暗影吞没真实——冥照！",
                "description": "将最后一发子弹类型反转",
                "use": self.use_mingzhao,
            },
            "言灵·时间零": {
                "category": "特殊", "rarity": "传说",
                "chant": "时间啊，停驻于此——时间零！",
                "description": "下一次开枪后仍保留行动权（冻结时间）",
                "use": self.use_shijianling,
            },
            "言灵·涡": {
                "category": "特殊", "rarity": "稀有",
                "chant": "万象流转，因果重洗——涡！",
                "description": "重新洗牌当前弹夹",
                "use": self.use_wo,
            },
            "言灵·冬": {
                "category": "特殊", "rarity": "稀有",
                "chant": "凛冬将至，万物冻结——冬！",
                "description": "将当前膛内最后一发子弹变为空包弹",
                "use": self.use_dong,
            },
            "言灵·梦貘": {
                "category": "特殊", "rarity": "稀有",
                "chant": "梦貘噬梦，记忆剥落——梦貘！",
                "description": "随机丢弃对方背包中的两个言灵",
                "use": self.use_mengpo,
            },
            "言灵·戒律": {
                "category": "特殊", "rarity": "稀有",
                "chant": "戒律如山，万言噤声——戒律！",
                "description": "令对方下一回合无法咏唱言灵",
                "use": self.use_jielv,
            },
            "言灵·皇帝": {
                "category": "特殊", "rarity": "传说",
                "chant": "皇帝临世，龙血臣服——皇帝！",
                "description": "彩蛋言灵：对方跳过下一回合，且你下一发子弹必定为龙炎弹",
                "use": self.use_huangdi,
            },
            "言灵·归墟": {
                "category": "特殊", "rarity": "传说",
                "chant": "万流归墟，一切终末——归墟！",
                "description": "将当前弹夹中所有龙炎弹变为空包弹",
                "use": self.use_gui_xu,
            },
            # ===== 新增扩充言灵 =====
            "言灵·莱茵": {
                "category": "攻击", "rarity": "传说",
                "chant": "莱茵长啸，核火焚天——莱茵！",
                "description": "对对方造成3点伤害，但自己也损失1点生命",
                "use": self.use_laiyin,
            },
            "言灵·湿婆业舞": {
                "category": "特殊", "rarity": "传说",
                "chant": "湿婆起舞，业火焚世——湿婆业舞！",
                "description": "双方各损失1点生命，并各随机丢弃一个言灵",
                "use": self.use_shishiyewu,
            },
            "言灵·钥匙": {
                "category": "辅助", "rarity": "传说",
                "chant": "万门皆启，诸禁皆开——钥匙！",
                "description": "查看对方所有言灵，并复制其中一个",
                "use": self.use_yaoshi,
            },
            "言灵·催眠": {
                "category": "特殊", "rarity": "稀有",
                "chant": "梦眼低垂，万念成空——催眠！",
                "description": "令对方下一回合无法发动龙血冲击",
                "use": self.use_cuimian,
            },
            "言灵·阴流": {
                "category": "辅助", "rarity": "稀有",
                "chant": "阴流无声，风刃潜行——阴流！",
                "description": "查看当前膛内子弹，并将其卸下",
                "use": self.use_yinliu,
            },
            # ===== 继续扩充的言灵 =====
            "言灵·吸血镰": {
                "category": "攻击", "rarity": "稀有",
                "chant": "吸血镰起，风刃噬魂——吸血镰！",
                "description": "对对方造成1点伤害，并偷走对方一个随机言灵",
                "use": self.use_xixuelian,
            },
            "言灵·八岐": {
                "category": "特殊", "rarity": "传说",
                "chant": "八岐临世，万梦崩碎——八岐！",
                "description": "随机丢弃对方两个言灵，并令对方下一回合无法咏唱言灵",
                "use": self.use_bayi,
            },
            "言灵·因陀罗": {
                "category": "攻击", "rarity": "传说",
                "chant": "因陀罗怒，雷帝降罚——因陀罗！",
                "description": "对对方造成3点伤害，并令对方下一回合无法发动龙血冲击",
                "use": self.use_yintuoluo,
            },
            "言灵·阴雷": {
                "category": "特殊", "rarity": "稀有",
                "chant": "阴雷暗涌，死寂破晓——阴雷！",
                "description": "将当前膛内最后一发子弹变为龙炎弹",
                "use": self.use_yinlei,
            },
            # ===== v1.9.0 新增言灵 =====
            "言灵·湮灭": {
                "category": "攻击", "rarity": "传说",
                "chant": "湮灭所至，因果崩解——湮灭！",
                "description": "对对方造成2点伤害，并将下一发子弹变为空包弹",
                "use": self.use_yianmie,
            },
            "言灵·怒焰": {
                "category": "攻击", "rarity": "稀有",
                "chant": "怒焰沸腾，焚尽八荒——怒焰！",
                "description": "本回合下一次龙血冲击伤害+1（可与双倍叠加）",
                "use": self.use_nuyan,
            },
            "言灵·蜕生": {
                "category": "防御", "rarity": "传说",
                "chant": "龙血不灭，涅槃蜕生——蜕生！",
                "description": "本局内死亡时以2点生命复活一次",
                "use": self.use_tuisheng,
            },
            "言灵·血鳞": {
                "category": "防御", "rarity": "稀有",
                "chant": "血鳞覆体，噬敌养身——血鳞！",
                "description": "免疫下一次受到的龙血冲击伤害，并恢复等量生命",
                "use": self.use_xuelin,
            },
            "言灵·黄金瞳": {
                "category": "辅助", "rarity": "传说",
                "chant": "黄金瞳开，万象皆明——黄金瞳！",
                "description": "下次受到龙血冲击伤害时免疫并全额反弹给攻击者",
                "use": self.use_huangjintong,
            },
            "言灵·血脉诅咒": {
                "category": "辅助", "rarity": "稀有",
                "chant": "血脉为咒，命途封锁——血脉诅咒！",
                "description": "令对方下一回合无法消耗生命抽取言灵",
                "use": self.use_xuemaizuzhou,
            },
            "言灵·轮回": {
                "category": "特殊", "rarity": "传说",
                "chant": "轮回颠倒，命运重写——轮回！",
                "description": "交换双方当前生命值",
                "use": self.use_lunhui,
            },
        }

        # 按稀有度/全量预构建抽取池，避免每次 random.choice(list(...)) 重建列表
        self.rarity_pools = {}
        for _name, _info in self.item_list.items():
            self.rarity_pools.setdefault(_info["rarity"], []).append(_name)
        self.item_names = list(self.item_list.keys())

    async def initialize(self):
        """插件激活时：加载龙币档案、恢复持久化对局并启动守护任务。"""
        self._load_economy()
        if self.config.get("persistGames"):
            self.load_games()
        try:
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())
        except RuntimeError:
            # 极端情况下无运行中的事件循环（如纯单元测试环境），守护任务不启动
            self._watchdog_task = None

    async def terminate(self):
        """插件停用时：保存对局并取消守护任务。"""
        if self.config.get("persistGames"):
            self.save_games()
        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except (asyncio.CancelledError, Exception):
                pass

    def get_channel_id(self, event: AstrMessageEvent) -> str:
        """
        获取唯一群聊ID（或session_id）。
        优先返回群ID；若为私聊，则返回session_id。
        """
        gid = event.get_group_id()
        if gid:
            return gid
        return event.session_id

    # ------------- 游戏基本指令 -------------
    @command_group("龙轮", alias={"龙族轮盘", "轮盘"})
    def dragon_roulette(self):
        """龙族轮盘游戏主指令组"""
        pass

    @dragon_roulette.command("规则", alias={"帮助"})
    async def show_rules(self, event: AstrMessageEvent):
        """查看简化版游戏规则。"""
        yield event.plain_result(textwrap.dedent("""\
            ══ 🐉 龙族轮盘 · 规则 ══
            【目标】让对方生命归零。
            【行动】
              发送“开枪/对方”攻击对方。
              发送“吞枪/自己”向自己开枪（空包弹可保留行动权并额外获言灵）。
              发送言灵名咏唱言灵。
              发送“抽”消耗生命抽取随机言灵。
              发送“认输”投降；发送“丢弃 言灵名”清理背包。
            【模式】
              /龙轮 模式 标准 / 极速 / 血牛 / 言灵乱斗 / 皇帝降临
            【抽卡】
              普通 60% / 稀有 30% / 传说 10%。
              保底：连续4抽未出稀有以上则下次必出稀有+；
                    连续8抽未出传说则下次必出传说。
              费用：首抽 2 血，之后每次抽卡消耗翻倍：2、4、8、16...
            【言灵】
              全部采用《龙族》原著言灵，含隐藏彩蛋“言灵·皇帝”。
              PvP 模式每轮每人最多使用 3 次言灵。
            【龙币】
              胜场 +30、参与 +10、连胜另有加成；
              对局开始前可发送“/龙轮 押 1|2 金额”下注，1:1 赔率，强制结束/超时则退还。
            【屠龙】
              单人挑战龙王：/龙轮 屠龙 列表 查看；/龙轮 屠龙 诺顿 发起（入场费 20 龙币）。
              组队讨伐：/龙轮 组队屠龙 诺顿 → /龙轮 组队加入 诺顿 → /龙轮 组队开始。
              击败 Boss 得 50~150 龙币；尼德霍格需先击败前三龙王解锁。
            指令简称：/龙轮 创建、/龙轮 加入、/龙轮 开始……
        """))

    @dragon_roulette.command("模式", alias={"选模式"})
    async def set_mode(self, event: AstrMessageEvent, mode: str):
        """
        设置游戏模式：标准 / 极速 / 血牛 / 言灵乱斗 / 皇帝降临。
        必须在开始游戏前设置。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有赌局，请先创建。")
            return
        if self.games[cid]["status"] == "started":
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n赌局已经开始，无法修改模式。")
            return
        valid_modes = ["标准", "极速", "血牛", "言灵乱斗", "皇帝降临"]
        if mode not in valid_modes:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n可选模式：" + "、".join(valid_modes))
            return
        self.games[cid]["mode"] = mode
        self._touch(cid)
        yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n当前模式已切换为【{mode}】！")

    @dragon_roulette.command("创建游戏", alias={"创建", "开"})
    async def create_game(self, event: AstrMessageEvent):
        """
        创建游戏：当本群中没有正在进行的游戏时可创建，
        创建后等待另一名玩家加入，超时自动取消。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            self.games[cid] = {
                "player1": self._new_player(event),
                "status": STATUS_WAITING,
                "mode": "标准",
                "origin": event.unified_msg_origin,  # 用于超时/守护任务主动通知
                "last_activity": time.time(),
                "game_token": time.time_ns(),  # 唯一令牌，防止旧超时任务误删新对局
            }
            asyncio.create_task(self.wait_for_join_timeout(cid, self.games[cid]["game_token"]))
            yield event.plain_result(textwrap.dedent(f"""\
                ══ 🐉 龙族轮盘 ══
                ——卡塞尔学院地下赌局——
                龙血在暗流中苏醒，言灵在血脉中低语。
                玩家1：{event.get_sender_name()} ({event.get_sender_id()})
                玩家2：正在等待中……

                请发送“/龙轮 加入”加入本游戏，超时后将自动取消！
            """))
        else:
            status = self.games[cid].get("status", "")
            if status == "waiting":
                yield event.plain_result("══ 🐉 龙族轮盘 ══\n本群已有赌局在等待玩家，请发送“/龙轮 加入”加入。")
            else:
                yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前群中已有赌局正在进行，无法重复创建。")

    async def wait_for_join_timeout(self, cid: str, game_token: int):
        """等待玩家2加入，超时则自动取消游戏（有押注则退还）"""
        await asyncio.sleep(self.config["maxWaitTime"])
        g = self.games.get(cid)
        # 仅当仍是同一局等待中的游戏时才取消，避免旧任务误删新对局
        if g and g.get("game_token") == game_token and g["status"] == STATUS_WAITING:
            origin = g.get("origin")
            name = g["player1"]["name"]
            refund = self._refund_bets(cid)
            del self.games[cid]
            if origin:
                msg = f"@{name}，等待玩家2超时，赌局已取消。"
                if refund:
                    msg += f"（押注已退还 {refund} 龙币）"
                await self.context.send_message(
                    origin,
                    MessageChain().message(msg)
                )

    @dragon_roulette.command("加入游戏", alias={"加入", "来"})
    async def join_game(self, event: AstrMessageEvent):
        """
        加入游戏：仅当游戏处于等待状态时可加入，
        且你不能加入自己创建的游戏。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有可加入的赌局，请先创建。")
            return
        if self.games[cid]["status"] != "waiting":
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n赌局已满或正在进行中。")
            return
        if self.games[cid]["player1"]["id"] == event.get_sender_id():
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n你不能加入自己创建的赌局。")
            return
        self.games[cid]["player2"] = self._new_player(event)
        self.games[cid]["status"] = STATUS_FULL
        self._touch(cid)
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            又一位混血种踏入赌局！
            玩家1：{self.games[cid]['player1']['name']} ({self.games[cid]['player1']['id']})
            玩家2：{event.get_sender_name()} ({event.get_sender_id()})

            请由玩家1发送“/龙轮 开始”以唤醒言灵，正式开始对战！
        """))

    def get_mode_config(self, mode: str) -> dict:
        """返回不同游戏模式的参数配置。"""
        configs = {
            "标准": {"hp": 8, "bullet_min": 3, "bullet_max": 8, "first_items": 1, "second_items": 2, "round_items": 1, "draw_offset": 1, "start_legend": False},
            "极速": {"hp": 4, "bullet_min": 3, "bullet_max": 5, "first_items": 0, "second_items": 1, "round_items": 1, "draw_offset": 1, "start_legend": False},
            "血牛": {"hp": 10, "bullet_min": 5, "bullet_max": 8, "first_items": 2, "second_items": 3, "round_items": 2, "draw_offset": 1, "start_legend": False},
            "言灵乱斗": {"hp": 6, "bullet_min": 4, "bullet_max": 7, "first_items": 4, "second_items": 5, "round_items": 2, "draw_offset": 0, "start_legend": False},
            "皇帝降临": {"hp": 6, "bullet_min": 3, "bullet_max": 8, "first_items": 2, "second_items": 3, "round_items": 1, "draw_offset": 1, "start_legend": True},
        }
        return configs.get(mode, configs["标准"])

    @dragon_roulette.command("开始游戏", alias={"开始", "战"})
    async def start_game(self, event: AstrMessageEvent):
        """
        开始游戏：仅允许游戏创建者（玩家1）操作，
        系统将随机生成弹夹、随机决定先后手，并为双方发放少量初始言灵。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n没有可开始的赌局，请先创建或加入。")
            return
        if self.games[cid]["status"] != "full":
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n赌局尚未凑满两人，无法开始。")
            return
        if self.games[cid]["player1"]["id"] != event.get_sender_id():
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n只有赌局创建者（玩家1）才能开始游戏。")
            return
        mode = self.games[cid].get("mode", "标准")
        cfg = self.get_mode_config(mode)
        self.games[cid]["mode"] = mode
        self.games[cid]["status"] = STATUS_STARTED
        self.games[cid]["bullet"] = generate_random_bullet_list(cfg["bullet_min"], cfg["bullet_max"])
        self.games[cid]["currentTurn"] = random.randint(1, 2)
        self.games[cid]["double"] = False
        self.games[cid]["round"] = 0
        self.games[cid]["usedHandcuff"] = False
        self.games[cid]["drawOffset"] = cfg["draw_offset"]
        self.games[cid]["roundItems"] = cfg["round_items"]
        self._touch(cid)

        # 按模式设置生命
        self.games[cid]["player1"]["hp"] = cfg["hp"]
        self.games[cid]["player2"]["hp"] = cfg["hp"]

        first_p = f"player{self.games[cid]['currentTurn']}"
        second_p = f"player{1 if self.games[cid]['currentTurn'] == 2 else 2}"
        # 按模式发放初始言灵
        for _ in range(cfg["first_items"]):
            self.games[cid][first_p]["items"].append(random.choice(self.item_names))
        for _ in range(cfg["second_items"]):
            self.games[cid][second_p]["items"].append(random.choice(self.item_names))
        # 皇帝降临模式：双方各获得一个随机传说言灵
        if cfg["start_legend"]:
            legends = self.rarity_pools[RARITY_LEGEND]
            for p in [first_p, second_p]:
                self.games[cid][p]["items"].append(random.choice(legends))

        bullet_list = self.games[cid]["bullet"]
        live_count = self.count_bullet(bullet_list, "实弹")
        blank_count = len(bullet_list) - live_count

        if os.path.exists(res_path("banner.png")):
            yield event.image_result(res_path("banner.png"))
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            ——言灵觉醒，赌局开始——
            模式：{mode}
            玩家1：{self.games[cid]["player1"]["name"]} ({self.games[cid]["player1"]["id"]})
            玩家2：{self.games[cid]["player2"]["name"]} ({self.games[cid]["player2"]["id"]})
            由 {self.at_id(self.games[cid][first_p]["name"])} 先手！
            初始言灵：先手 {cfg["first_items"]} 个，后手 {cfg["second_items"]} 个。

            🔫 炼金手枪已装填 {len(bullet_list)} 发弹：
            🔥 龙炎弹 {live_count} 发 ｜ 💨 空包弹 {blank_count} 发

            回合内可发送“抽”消耗生命补充言灵。
            请发送“/龙轮 信息”查看详细情况，祝你好运！
        """))

    @dragon_roulette.command("对战信息", alias={"信息", "状态"})
    async def show_game_info(self, event: AstrMessageEvent):
        """
        查看对战信息：显示双方当前血量和持有的言灵情况。
        优先输出 Pillow 渲染的对战面板图片；渲染失败时回退为完整纯文本。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != "started":
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有正在进行的赌局。")
            return
        g = self.games[cid]
        p1 = g["player1"]
        p2 = g["player2"]
        cur_p = f"player{g['currentTurn']}"
        mode = g.get("mode", "标准")
        cfg = self.get_mode_config(mode)
        cur_cost = DRAW_BASE_COST * (DRAW_COST_MULTIPLIER ** g[cur_p]["drawCount"])
        bullets = g.get("bullet", [])
        live = self.count_bullet(bullets, BULLET_LIVE)
        blank = len(bullets) - live
        bets_line = ""
        bets = g.get("bets", [])
        if bets:
            p1_total = sum(b["amount"] for b in bets if b["side"] == "player1")
            p2_total = sum(b["amount"] for b in bets if b["side"] == "player2")
            state = "已封盘" if g["status"] == STATUS_STARTED else "可下注"
            bets_line = f"💰 押注：玩家1 {p1_total} ｜ 玩家2 {p2_total} 龙币（{state}）"

        img_path = self._render_battle_panel(g)
        if img_path:
            yield event.image_result(img_path)
            msg = textwrap.dedent(f"""\
                ══ 🐉 龙族轮盘 ══
                模式：{mode}{(' ｜ 讨伐队 ' + str(len(g['team_members'])) + '人') if g.get('team_hunt') else ''} ｜ 弹夹剩余 {len(bullets)} 发（🔥 {live} ｜ 💨 {blank}）｜ 第 {g.get("round", 1)} 轮
                ▶ 当前行动者：{self.at_id(g[cur_p]["name"])} ｜ 下次抽卡 {cur_cost} 血 ｜ 言灵 {g[cur_p].get('usedItems', 0)}/{PVP_MAX_ITEMS_PER_ROUND} ｜ 保底 稀有 {g[cur_p]['pity']}/4 传说 {g[cur_p]['legendPity']}/8
            """)
            if bets_line:
                msg += bets_line + "\n"
            msg += "✨ 发送“开枪/对方”攻击，“吞枪/自己”开枪，“抽”抽卡，言灵名咏唱，“认输”投降。"
            yield event.plain_result(msg)
            return

        # ---- 纯文本回退（无 Pillow / 无中文字体时）----
        msg = textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            模式：{mode}{(' ｜ 讨伐队 ' + str(len(g.get('team_members', []))) + '人') if g.get('team_hunt') else ''} ｜ 弹夹剩余 {len(bullets)} 发
            -- 💖 生命状况 --
        """)
        if g.get("team_hunt"):
            for idx, m in enumerate(g["team_members"]):
                mark = "▶" if m["id"] == g[cur_p]["id"] else f"{idx + 1}."
                msg += f"{mark} {m['name']}：{m['hp']}/{cfg['hp']} {self.status_text(m)}\n"
            msg += f"🐲 {p2['name']}：{p2['hp']}/{g.get('bossMaxHp', cfg['hp'])} {self.status_text(p2)}"
        else:
            msg += f"🐉 {p1['name']}：{p1['hp']}/{cfg['hp']} {self.status_text(p1)}\n"
            msg += f"🐲 {p2['name']}：{p2['hp']}/{g.get('bossMaxHp', cfg['hp'])} {self.status_text(p2)}"
        msg += textwrap.dedent(f"""\

            -- 🎴 抽卡 --
            当前行动者下次抽取代价：{cur_cost} 点生命（本回合已抽 {g[cur_p]["drawCount"]} 次）
            言灵使用：{g[cur_p].get('usedItems', 0)}/{PVP_MAX_ITEMS_PER_ROUND}（PvP 每轮上限）
            保底进度：稀有 {g[cur_p]["pity"]}/4 ｜ 传说 {g[cur_p]["legendPity"]}/8
        """)
        if g.get("team_hunt"):
            for m in g["team_members"]:
                msg += f"\n-- 📜 {m['name']} 的言灵 ({len(m['items'])}/8) --\n"
                msg += "\n".join(f"  {it}｜{self.item_list[it]['description']}" for it in m["items"])
        else:
            msg += f"\n-- 📜 {p1['name']} 的言灵 ({len(p1['items'])}/8) --\n"
            msg += "\n".join(f"  {it}｜{self.item_list[it]['description']}" for it in p1["items"])
            msg += f"\n-- 📜 {p2['name']} 的言灵 ({len(p2['items'])}/8) --\n"
            msg += "\n".join(f"  {it}｜{self.item_list[it]['description']}" for it in p2["items"])
        if bets_line:
            msg += "\n" + bets_line
        msg += textwrap.dedent("""\n
            ✨ 发送“开枪/对方”攻击对方，“吞枪/自己”向自己开枪；
            ✨ 发送言灵名咏唱言灵；
            ✨ 发送“抽”消耗生命抽取言灵；
            ✨ 发送“认输”投降；发送“丢弃 言灵名”清理背包。
        """)
        yield event.plain_result(msg)

    @dragon_roulette.command("言灵图鉴", alias={"图鉴", "灵"})
    async def show_grimoire(self, event: AstrMessageEvent):
        """查看全部可用言灵及效果（按分类美化展示，并附带分类图鉴图片）。"""
        category_titles = {
            "攻击": "🔥 攻击系言灵",
            "防御": "🛡️ 防御系言灵",
            "辅助": "✨ 辅助系言灵",
            "特殊": "🌀 特殊系言灵",
        }
        rarity_marks = {"普通": "◆", "稀有": "★★", "传说": "★★★"}
        if os.path.exists(res_path("grimoire.png")):
            yield event.image_result(res_path("grimoire.png"))
        lines = [
            "══ 🐉 龙族轮盘 · 言灵图鉴 ══",
            "——卡塞尔学院混血种秘传，共 {} 种——".format(len(self.item_list)),
            ""
        ]
        for cat in ["攻击", "防御", "辅助", "特殊"]:
            lines.append(f"【{category_titles[cat]}】")
            for name, info in self.item_list.items():
                if info["category"] != cat:
                    continue
                lines.append(f"  {rarity_marks.get(info['rarity'], '◆')} {name}")
                lines.append(f"    └ {info['description']}")
                lines.append(f"    └ 咏唱：{info['chant']}")
            lines.append("")
        yield event.plain_result("\n".join(lines))
        # 补全图鉴图片：每个分类一张
        for cat, fname in [("攻击", "grimoire_attack.png"), ("防御", "grimoire_defense.png"),
                           ("辅助", "grimoire_assist.png"), ("特殊", "grimoire_special.png")]:
            if os.path.exists(res_path(fname)):
                yield event.image_result(res_path(fname))

    @dragon_roulette.command("抽言灵", alias={"抽取", "抽卡", "抽"})
    async def draw_item(self, event: AstrMessageEvent):
        """
        抽言灵：当前回合玩家可以消耗生命抽取随机言灵。
        费用：首抽 2 血，之后每次抽卡消耗翻倍：2、4、8、16...
        稀有度：普通60% / 稀有30% / 传说10%；有保底。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != "started":
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有正在进行的赌局。")
            return
        g = self.games[cid]
        cur_p = f"player{g['currentTurn']}"
        if g[cur_p]["id"] != event.get_sender_id():
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n现在不是你的回合，无法抽取言灵。")
            return
        if g[cur_p].get("noDraw", False):
            yield event.plain_result("🚫 你被【血脉诅咒】缠绕，本回合无法消耗生命抽取言灵！")
            return
        if len(g[cur_p]["items"]) >= ITEM_CAP:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n你的言灵背包已满（上限8），无法再抽取。")
            return
        cost = DRAW_BASE_COST * (DRAW_COST_MULTIPLIER ** g[cur_p]["drawCount"])
        if g[cur_p]["hp"] <= cost:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n你的生命不足以支付 {cost} 点代价，无法抽取言灵。")
            return

        # 计算稀有度
        rarity = None
        if g[cur_p]["legendPity"] >= 7:
            rarity = RARITY_LEGEND
        elif g[cur_p]["pity"] >= 3:
            rarity = RARITY_RARE if random.random() < 0.6 else RARITY_LEGEND
        else:
            roll = random.random()
            if roll < 0.10:
                rarity = RARITY_LEGEND
            elif roll < 0.40:
                rarity = RARITY_RARE
            else:
                rarity = RARITY_COMMON

        # 更新保底
        if rarity == RARITY_LEGEND:
            g[cur_p]["legendPity"] = 0
            g[cur_p]["pity"] = 0
        elif rarity == RARITY_RARE:
            g[cur_p]["pity"] = 0
            g[cur_p]["legendPity"] += 1
        else:
            g[cur_p]["pity"] += 1
            g[cur_p]["legendPity"] += 1

        g[cur_p]["hp"] -= cost
        g[cur_p]["drawCount"] += 1
        new_item = random.choice(self.rarity_pools[rarity])
        g[cur_p]["items"].append(new_item)
        self._touch(cid)

        rarity_icon = RARITY_ICONS.get(rarity, "◆")
        max_hp = self.get_mode_config(g.get("mode", "标准"))["hp"]
        if os.path.exists(res_path("draw_card.png")):
            yield event.image_result(res_path("draw_card.png"))
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            你割破手腕，以 {cost} 点生命为代价，让龙血在虚空中沸腾……
            新的言灵印记浮现：【{new_item}】（{rarity_icon} {rarity}）！
            当前生命：{g[cur_p]["hp"]}/{max_hp}
            保底进度：稀有 {g[cur_p]["pity"]}/4 ｜ 传说 {g[cur_p]["legendPity"]}/8
        """))

    @dragon_roulette.command("结束游戏", alias={"结束", "散"})
    async def end_game(self, event: AstrMessageEvent):
        """
        结束游戏：允许游戏参与者或管理员主动结束当前游戏。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有可结束的赌局。")
            return
        g = self.games[cid]
        if g.get("team_hunt"):
            allowed_ids = [m["id"] for m in g.get("team_members", [])] + self.config["admin"]
        else:
            allowed_ids = [g.get("player1", {}).get("id", ""), g.get("player2", {}).get("id", "")] + self.config["admin"]
        if event.get_sender_id() not in allowed_ids:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n只有赌局参与者或管理员可以结束游戏。")
            return
        for ln in self.void_game(cid, f"{self.at_id(event.get_sender_name())} 已强制结束当前赌局，本局作废。"):
            yield event.plain_result(ln)

    @dragon_roulette.command("认输", alias={"投降", "投"})
    async def surrender(self, event: AstrMessageEvent):
        """
        认输：本局参与者可主动认输，对方直接获胜。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != STATUS_STARTED:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有正在进行中的赌局。")
            return
        g = self.games[cid]
        sender = event.get_sender_id()
        loser = None
        if g.get("team_hunt"):
            if any(m["id"] == sender for m in g.get("team_members", [])):
                loser = "player1"
            else:
                yield event.plain_result("══ 🐉 龙族轮盘 ══\n只有讨伐队成员可以认输。")
                return
        elif g["player1"]["id"] == sender:
            loser = "player1"
        elif "player2" in g and g["player2"]["id"] == sender:
            loser = "player2"
        else:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n只有本局参与者可以认输。")
            return
        winner = other_player(loser)
        yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n{g[loser]['name']} 放下了手中的炼金手枪，选择认输。")
        for ln in self.game_over(cid, winner=winner, loser=loser):
            yield event.plain_result(ln)

    @dragon_roulette.command("丢弃", alias={"扔", "弃"})
    async def discard_item(self, event: AstrMessageEvent, item: str):
        """
        丢弃：丢弃自己背包中的指定言灵，为新的言灵腾出空间。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != STATUS_STARTED:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有正在进行中的赌局。")
            return
        g = self.games[cid]
        player = None
        if g.get("team_hunt"):
            for m in g.get("team_members", []):
                if m["id"] == event.get_sender_id():
                    player = m
                    break
        else:
            for p in ("player1", "player2"):
                if p in g and g[p]["id"] == event.get_sender_id():
                    player = g[p]
                    break
        if not player:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n你不在本局游戏中。")
            return
        if item not in player["items"]:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n你的背包中没有【{item}】。")
            return
        player["items"].remove(item)
        self._touch(cid)
        yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n你主动遗忘了【{item}】，为新的言灵腾出了空间。")

    # ------------- 龙币：押注 / 排行榜 / 战绩 -------------
    @dragon_roulette.command("押注", alias={"押", "下注"})
    async def bet(self, event: AstrMessageEvent, side: str, amount: str):
        """
        押注：对局开始前押玩家1或玩家2，1:1 赔率。
        用法：/龙轮 押 1 50（押玩家1 50 龙币）；/龙轮 押 2 100
        """
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有赌局，无法下注。")
            return
        g = self.games[cid]
        if g["status"] == STATUS_STARTED:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n赌局已经开始，押注已封盘！")
            return
        s = side.strip().lower()
        if s in ("1", "a", "玩家1", "先手", "p1"):
            side_key = "player1"
        elif s in ("2", "b", "玩家2", "后手", "p2"):
            side_key = "player2"
        else:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n请押 1（玩家1）或 2（玩家2）。")
            return
        if side_key == "player2" and "player2" not in g:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n玩家2尚未加入，还不能押他。")
            return
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n金额需为整数龙币。")
            return
        if amount <= 0:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n金额需大于 0。")
            return
        uid = event.get_sender_id()
        u = self._get_user(uid, event.get_sender_name())
        if u["coins"] < amount:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n你的龙币不足（当前 {u['coins']}）。")
            return
        u["coins"] -= amount  # 先锁定本金，结算时赢家返还本金+赢额
        g.setdefault("bets", []).append({
            "uid": uid,
            "name": event.get_sender_name(),
            "side": side_key,
            "amount": amount,
        })
        self._save_economy()
        self._touch(cid)
        side_name = "玩家1" if side_key == "player1" else "玩家2"
        yield event.plain_result(
            f"══ 🐉 龙族轮盘 ══\n{event.get_sender_name()} 押了 {amount} 龙币在【{side_name}】身上，坐等开牌！"
        )

    @dragon_roulette.command("排行榜", alias={"排行", "榜"})
    async def leaderboard(self, event: AstrMessageEvent):
        """查看龙币排行榜（前十）。"""
        if not self.economy:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n还没有任何龙币记录，快去赢下第一局吧！")
            return
        top = sorted(self.economy.values(), key=lambda u: u.get("coins", 0), reverse=True)[:10]
        medals = ["🥇", "🥈", "🥉"]
        lines = ["══ 🐉 龙族轮盘 · 龙币榜 ══", "——卡塞尔赌场通缉令——"]
        for i, u in enumerate(top):
            mark = medals[i] if i < 3 else f"{i + 1}."
            total = u.get("wins", 0) + u.get("losses", 0)
            wr = f"{u.get('wins', 0) / total * 100:.0f}%" if total else "-"
            lines.append(
                f"{mark} {u.get('name', '匿名')}：{u.get('coins', 0)} 龙币 ｜ "
                f"{u.get('wins', 0)}胜{u.get('losses', 0)}负（{wr}）｜ 连胜{u.get('streak', 0)}"
            )
        yield event.plain_result("\n".join(lines))

    @dragon_roulette.command("战绩", alias={"我", "我的战绩"})
    async def my_stats(self, event: AstrMessageEvent):
        """查看自己的龙币与战绩。"""
        uid = event.get_sender_id()
        u = self._get_user(uid, event.get_sender_name())
        total = u.get("wins", 0) + u.get("losses", 0)
        wr = f"{u.get('wins', 0) / total * 100:.1f}%" if total else "-"
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 · 战绩 ══
            {event.get_sender_name()} 的赌场档案：
            💰 龙币：{u.get('coins', 0)}
            🏆 战绩：{u.get('wins', 0)} 胜 / {u.get('losses', 0)} 负（胜率 {wr}）
            🔥 当前连胜：{u.get('streak', 0)} ｜ 最高连胜：{u.get('max_streak', 0)}
            🎯 押注：押中 {u.get('bets_won', 0)} 次 / 押失 {u.get('bets_lost', 0)} 次
        """))

    # ------------- 屠龙模式（PvE 单挑龙王） -------------
    @dragon_roulette.command("屠龙", alias={"单挑", "讨伐", "狩猎"})
    async def dragon_hunt(self, event: AstrMessageEvent, boss: str = ""):
        """
        单人挑战龙王 Boss。
        用法：/龙轮 屠龙 列表（查看 Boss）；/龙轮 屠龙 诺顿（发起挑战）
        """
        cid = self.get_channel_id(event)
        uid = event.get_sender_id()
        boss = (boss or "").strip()
        fee = self.config.get("dragonFee", 20)
        rewards = self.config.get("dragonRewards", [50, 80, 100, 150])
        u = self._get_user(uid, event.get_sender_name())
        kills = u.get("bosses", {})

        # 列表模式
        if boss in ("", "列表", "查看", "list", "图鉴"):
            lines = [
                "══ 🐉 龙族轮盘 · 屠龙深渊 ══",
                "——尼伯龙根深处，龙王们正在等待——",
                "",
            ]
            for idx, key in enumerate(BOSS_ORDER):
                b = BOSSES[key]
                locked = key == "尼德霍格" and not all(kills.get(k, 0) >= 1 for k in BOSS_ORDER[:3])
                kill_info = f"已讨伐 {kills.get(key, 0)} 次" if kills.get(key, 0) else "未讨伐"
                lock = "（🔒 需击败前三龙王解锁）" if locked else ""
                lines.append(f"{idx + 1}. {b['name']} ｜ HP {b['hp']} ｜ 奖励 {rewards[idx]} 龙币 ｜ {kill_info} {lock}")
            lines.append("")
            lines.append(f"发送“/龙轮 屠龙 名字”发起挑战（入场费 {fee} 龙币）。")
            lines.append(f"组队：发送“/龙轮 组队屠龙 名字”创建讨伐房间（2~{TEAM_MAX_SIZE} 人）。")
            yield event.plain_result("\n".join(lines))
            return

        if boss not in BOSSES:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n没有这个龙王。可选：诺顿 / 芬里厄 / 伊邪那美 / 尼德霍格。")
            return
        if cid in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前已有赌局进行中，先结束它再屠龙吧。")
            return
        if u["coins"] < fee:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n入场费 {fee} 龙币，你的龙币不足（当前 {u['coins']}）。")
            return
        if boss == "尼德霍格":
            if not all(kills.get(k, 0) >= 1 for k in BOSS_ORDER[:3]):
                yield event.plain_result("══ 🐉 龙族轮盘 ══\n尼德霍格沉睡在深渊最底层——先击败诺顿、芬里厄、伊邪那美才能唤醒它！")
                return

        b = BOSSES[boss]
        reward = rewards[BOSS_ORDER.index(boss)]
        u["coins"] -= fee
        human = self._new_player(event)
        boss_p = self._new_player(event)
        boss_p["name"] = b["name"]
        boss_p["hp"] = b["hp"]
        boss_p["items"] = list(b["skills"])
        cfg = self.get_mode_config("标准")
        human["hp"] = cfg["hp"]
        human["items"] = [random.choice(self.item_names) for _ in range(cfg["first_items"])]
        g = {
            "player1": human,
            "player2": boss_p,
            "status": STATUS_STARTED,
            "mode": "屠龙",
            "boss": boss,
            "bossMaxHp": b["hp"],
            "origin": event.unified_msg_origin,
            "last_activity": time.time(),
            "currentTurn": 1,
            "bullet": generate_random_bullet_list(cfg["bullet_min"], cfg["bullet_max"]),
            "double": False,
            "round": 0,
            "usedHandcuff": False,
            "drawOffset": cfg["draw_offset"],
            "roundItems": cfg["round_items"],
        }
        self.games[cid] = g
        self._save_economy()
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 · 屠龙 ══
            你踏入了尼伯龙根的深渊，直面【{b['name']}】！
            {b['desc']}
            Boss 血量：{b['hp']} ｜ 你的血量：{cfg['hp']} ｜ 先手：你
            已支付入场费 {fee} 龙币，击败 Boss 可得 {reward} 龙币！
            发送“开枪/对方”攻击，“吞枪/自己”开枪，“抽”抽卡，言灵名咏唱，“信息”查看面板。
            Boss 的回合将自动行动，无需等待。
        """))

    # ------------- 组队屠龙（PvE 组队讨伐） -------------
    async def _team_wait_timeout(self, cid: str, token: int):
        """组队房间等待超时：只取消同一 token 的等待房。"""
        await asyncio.sleep(self.config["maxWaitTime"])
        g = self.games.get(cid)
        if g and g.get("team_hunt") and g.get("game_token") == token and g.get("status") == STATUS_WAITING:
            origin = g.get("origin")
            name = g["team_members"][0]["name"] if g.get("team_members") else ""
            del self.games[cid]
            if origin:
                try:
                    await self.context.send_message(origin, MessageChain().message(f"@{name}，组队讨伐等待超时，房间已取消。"))
                except Exception:
                    pass

    @dragon_roulette.command("组队屠龙", alias={"组队讨伐", "组队"})
    async def team_create(self, event: AstrMessageEvent, boss: str = ""):
        """
        创建组队讨伐房间。
        用法：/龙轮 组队屠龙 诺顿
        """
        boss = (boss or "").strip()
        cid = self.get_channel_id(event)
        if boss in ("", "列表", "查看", "list", "图鉴"):
            async for ln in self.dragon_hunt(event, "列表"):
                yield ln
            return
        if boss not in BOSSES:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n没有这个龙王。可选：诺顿 / 芬里厄 / 伊邪那美 / 尼德霍格。")
            return
        if cid in self.games:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前已有赌局或讨伐房间进行中，请先结束。")
            return
        u = self._get_user(event.get_sender_id(), event.get_sender_name())
        if boss == "尼德霍格":
            kills = u.get("bosses", {})
            if not all(kills.get(k, 0) >= 1 for k in BOSS_ORDER[:3]):
                yield event.plain_result("══ 🐉 龙族轮盘 ══\n尼德霍格沉睡在深渊最底层——先击败诺顿、芬里厄、伊邪那美才能唤醒它！")
                return
        if u["coins"] < self.config.get("dragonFee", 20):
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n你的龙币不足以支付入场费（当前 {u['coins']}）。")
            return
        g = {
            "team_hunt": True,
            "status": STATUS_WAITING,
            "boss": boss,
            "team_members": [self._new_player(event)],
            "creator": event.get_sender_id(),
            "origin": event.unified_msg_origin,
            "last_activity": time.time(),
            "game_token": time.time_ns(),
        }
        self.games[cid] = g
        asyncio.create_task(self._team_wait_timeout(cid, g["game_token"]))
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 · 组队讨伐 ══
            你创建了【{BOSSES[boss]['name']}】的讨伐房间！
            当前人数：1/{TEAM_MAX_SIZE}
            请发送“/龙轮 组队加入 {boss}”加入，发送“/龙轮 组队开始”开始战斗。
            超时未开始将自动取消（{self.config.get('maxWaitTime', 180)} 秒）。
        """))

    @dragon_roulette.command("组队加入", alias={"加入讨伐"})
    async def team_join(self, event: AstrMessageEvent, boss: str = ""):
        """加入组队讨伐房间。用法：/龙轮 组队加入 诺顿"""
        cid = self.get_channel_id(event)
        g = self.games.get(cid)
        if not g or not g.get("team_hunt") or g.get("status") != STATUS_WAITING:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有等待中的组队讨伐房间。")
            return
        boss = (boss or "").strip()
        if boss and boss != g["boss"]:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n当前讨伐对象是【{BOSSES[g['boss']]['name']}】，不能加入其他龙王。")
            return
        if len(g["team_members"]) >= TEAM_MAX_SIZE:
            yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n讨伐队已满（{TEAM_MAX_SIZE} 人）。")
            return
        if any(m["id"] == event.get_sender_id() for m in g["team_members"]):
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n你已经在这个讨伐队里了。")
            return
        g["team_members"].append(self._new_player(event))
        self._touch(cid)
        yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n{event.get_sender_name()} 加入讨伐队！当前人数：{len(g['team_members'])}/{TEAM_MAX_SIZE}")

    @dragon_roulette.command("组队开始", alias={"开始讨伐"})
    async def team_start(self, event: AstrMessageEvent):
        """开始组队讨伐。用法：/龙轮 组队开始"""
        cid = self.get_channel_id(event)
        g = self.games.get(cid)
        if not g or not g.get("team_hunt") or g.get("status") != STATUS_WAITING:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n当前没有可开始的组队讨伐房间。")
            return
        if g.get("creator") != event.get_sender_id():
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n只有房间创建者可以开始讨伐。")
            return
        if len(g["team_members"]) < 2:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n组队讨伐至少需要 2 名队员。")
            return

        boss = g["boss"]
        fee = self.config.get("dragonFee", 20)
        rewards = self.config.get("dragonRewards", [50, 80, 100, 150])
        # 尼德霍格需要所有队员都解锁
        if boss == "尼德霍格":
            for m in g["team_members"]:
                u = self._get_user(m["id"], m["name"])
                kills = u.get("bosses", {})
                if not all(kills.get(k, 0) >= 1 for k in BOSS_ORDER[:3]):
                    yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n队员 {m['name']} 尚未击败前三龙王，无法讨伐尼德霍格。")
                    return
        # 检查并扣除每个队员入场费
        for m in g["team_members"]:
            u = self._get_user(m["id"], m["name"])
            if u["coins"] < fee:
                yield event.plain_result(f"══ 🐉 龙族轮盘 ══\n队员 {m['name']} 龙币不足（当前 {u['coins']}），无法开始。")
                return
        for m in g["team_members"]:
            self._get_user(m["id"], m["name"])["coins"] -= fee

        b = BOSSES[boss]
        n = len(g["team_members"])
        boss_hp = b["hp"] + TEAM_BOSS_HP_PER_EXTRA * (n - 1)
        boss_p = self._new_player(event)
        boss_p["name"] = b["name"]
        boss_p["hp"] = boss_hp
        boss_p["items"] = list(b["skills"])

        cfg = self.get_mode_config("标准")
        for m in g["team_members"]:
            m["hp"] = cfg["hp"]
            m["items"] = [random.choice(self.item_names) for _ in range(cfg["first_items"])]

        reward = rewards[BOSS_ORDER.index(boss)]
        share = max(1, reward // n)
        g.update({
            "player1": g["team_members"][0],
            "player2": boss_p,
            "team_index": 0,
            "status": STATUS_STARTED,
            "mode": "屠龙",
            "bossMaxHp": boss_hp,
            "bossPower": n - 1,   # 每多一人，Boss 龙炎弹伤害 +1
            "currentTurn": 1,
            "bullet": generate_random_bullet_list(cfg["bullet_min"], cfg["bullet_max"]),
            "double": False,
            "round": 0,
            "usedHandcuff": False,
            "drawOffset": cfg["draw_offset"],
            "roundItems": cfg["round_items"],
            "last_activity": time.time(),
        })
        self._save_economy()
        names = "、".join(m["name"] for m in g["team_members"])
        yield event.plain_result(textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 · 组队讨伐 ══
            讨伐队集结完毕，直面【{b['name']}】！
            队员：{names}
            Boss 血量：{boss_hp}（因人数强化）｜ 每人血量：{cfg['hp']} ｜ 先手：{g['team_members'][0]['name']}
            每人已支付入场费 {fee} 龙币，胜利后每人可分得 {share} 龙币！
            队员将轮流行动，Boss 在全体队员行动后自动反击。
            发送“开枪/对方”攻击，“吞枪/自己”开枪，“抽”抽卡，言灵名咏唱，“信息”查看面板。
        """))

    # ------------- 言灵兑换功能 -------------
    @dragon_roulette.command("兑换", alias={"换"})
    async def exchange_item(self, event: AstrMessageEvent, source: str, target: str):
        """
        兑换言灵：如果你拥有2个相同的【source】言灵，则可兑换为1个【target】言灵。
        """
        allowed_exchanges = {
            "言灵·圣裁": ["言灵·君焰", "言灵·风王之瞳", "言灵·雷池", "言灵·青铜御座", "言灵·王之侍", "言灵·炽日", "言灵·深血", "言灵·阴流"],
            "言灵·无尘之地": ["言灵·王权", "言灵·青铜御座", "言灵·冬", "言灵·王之侍", "言灵·阴流"],
            "言灵·君焰": ["言灵·冥照", "言灵·涡", "言灵·黑炎牢狱", "言灵·莱茵"],
            "言灵·风王之瞳": ["言灵·先知", "言灵·蛇", "言灵·刹那", "言灵·阴流"],
            "言灵·镜瞳": ["言灵·镰鼬", "言灵·血脉牵引", "言灵·钥匙"],
            "言灵·雷池": ["言灵·审判", "言灵·梦貘", "言灵·戒律", "言灵·莱茵"],
            "言灵·炽日": ["言灵·烛龙", "言灵·催眠"],
            "言灵·深血": ["言灵·炽日"],
            "言灵·镰鼬": ["言灵·钥匙"],
        }
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != "started":
            yield event.plain_result("当前没有正在进行的赌局。")
            return
        if source not in allowed_exchanges or target not in allowed_exchanges[source]:
            yield event.plain_result(f"【{source}】无法兑换成【{target}】。")
            return
        game = self.games[cid]
        cur_player = f"player{game['currentTurn']}"
        if event.get_sender_id() != game[cur_player]["id"]:
            yield event.plain_result("只有当前行动玩家可以兑换言灵。")
            return
        if game[cur_player]["items"].count(source) < 2:
            yield event.plain_result(f"你没有足够的【{source}】进行兑换（需要2个）。")
            return
        for _ in range(2):
            game[cur_player]["items"].remove(source)
        game[cur_player]["items"].append(target)
        self._touch(cid)
        yield event.plain_result(f"兑换成功：2个【{source}】已兑换为1个【{target}】！")

    # ------------- Debug 模式（仅管理员可用） -------------
    @dragon_roulette.group("debug", alias={"dbg"})
    def debug(self):
        """Debug模式：仅限管理员使用，用于给玩家言灵、修改血量、查询状态等"""
        pass

    @debug.command("给言灵", alias={"给"})
    async def debug_give_item(self, event: AstrMessageEvent, target: str, item: str, quantity: int):
        if event.get_sender_id() not in self.config["admin"]:
            yield event.plain_result("权限不足！")
            return
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("当前群中没有赌局。")
            return
        game = self.games[cid]
        player = None
        if game["player1"]["id"] == target:
            player = game["player1"]
        elif "player2" in game and game["player2"]["id"] == target:
            player = game["player2"]
        if not player:
            yield event.plain_result("指定的玩家不在当前赌局中。")
            return
        for _ in range(quantity):
            player["items"].append(item)
        yield event.plain_result(f"已给玩家 {player['name']} 添加了 {quantity} 个【{item}】。")

    @debug.command("修改血量", alias={"血量"})
    async def debug_set_hp(self, event: AstrMessageEvent, target: str, hp: int):
        if event.get_sender_id() not in self.config["admin"]:
            yield event.plain_result("权限不足！")
            return
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("当前群中没有赌局。")
            return
        game = self.games[cid]
        player = None
        if game["player1"]["id"] == target:
            player = game["player1"]
        elif "player2" in game and game["player2"]["id"] == target:
            player = game["player2"]
        if not player:
            yield event.plain_result("指定的玩家不在当前赌局中。")
            return
        player["hp"] = hp
        yield event.plain_result(f"已将玩家 {player['name']} 的血量设置为 {hp}。")

    @debug.command("查询子弹", alias={"子弹"})
    async def debug_query_bullet(self, event: AstrMessageEvent):
        if event.get_sender_id() not in self.config["admin"]:
            yield event.plain_result("权限不足！")
            return
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("当前群中没有赌局。")
            return
        bullet_list = self.games[cid].get("bullet", [])
        yield event.plain_result(f"当前弹夹：{bullet_list}")

    @debug.command("查询游戏", alias={"查询"})
    async def debug_query_game(self, event: AstrMessageEvent):
        if event.get_sender_id() not in self.config["admin"]:
            yield event.plain_result("权限不足！")
            return
        cid = self.get_channel_id(event)
        if cid not in self.games:
            yield event.plain_result("当前群中没有赌局。")
            return
        yield event.plain_result(f"当前游戏数据：{self.games[cid]}")

    # ------------- 消息监听 -------------
    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """
        监听消息：如果游戏正在进行且处于当前玩家回合，
        则判断玩家是否选择了“自己”或“对方”发动龙血冲击，或施展言灵。
        """
        cid = self.get_channel_id(event)
        if cid not in self.games or self.games[cid]["status"] != "started":
            return
        g = self.games[cid]
        cur_player = f"player{g['currentTurn']}"
        if g[cur_player]["id"] != event.get_sender_id():
            return
        content = event.message_obj.message_str.strip()
        if content in ["自己", "对方", "吞枪", "开枪"]:
            if g[cur_player].get("hypnotized", False):
                yield event.plain_result("😴 你被【催眠】控制，暂时无法发动龙血冲击！")
                return
            target = "自己" if content in ["自己", "吞枪"] else "对方"
            async for msg_ret in self.fire(cid, target, event):
                yield msg_ret
            return
        if content in ["抽", "抽卡", "抽取", "抽言灵"]:
            async for msg_ret in self.draw_item(event):
                yield msg_ret
            return
        if content in g[cur_player]["items"]:
            if g[cur_player].get("silenced", False):
                yield event.plain_result("🔇 你被【戒律】压制，暂时无法咏唱言灵！")
                return
            async for msg_ret in self.use_item(cid, content, event):
                yield msg_ret

    # ------------- 核心函数：龙血冲击（原开枪） -------------
    async def fire(self, cid: str, target: str, event: AstrMessageEvent):
        """
        龙血冲击：凝聚龙血与言灵，通过炼金手枪释放。
        根据膛中子弹类型计算伤害、切换回合或结束游戏。
        """
        game = self.games[cid]
        self._touch(cid)
        cur_p = f"player{game['currentTurn']}"
        oth_p = f"player{1 if game['currentTurn'] == 2 else 2}"
        bullet = game["bullet"].pop() if game["bullet"] else None
        if not bullet:
            yield event.plain_result("══ 🐉 龙族轮盘 ══\n炼金手枪的弹夹已空，自动进入下一轮。")
            yield event.plain_result(self.next_round(game))
            return

        # 戒律沉默在开枪后消散
        if game[cur_p].get("silenced", False):
            game[cur_p]["silenced"] = False
        # 催眠状态如果仍存在，开枪时也会消散（正常情况在消息层已被拦截）
        if game[cur_p].get("hypnotized", False):
            game[cur_p]["hypnotized"] = False

        # 烛龙：将下一发变为龙炎弹
        next_live_msg = ""
        if game[cur_p].get("nextLive", False):
            game[cur_p]["nextLive"] = False
            if bullet == "空包弹":
                bullet = "实弹"
                next_live_msg = "【烛龙】龙炎吞没空包弹，化为龙炎弹！\n"
            else:
                next_live_msg = "【烛龙】龙炎弹威势更盛！\n"

        text = (
            f"══ 🐉 龙族轮盘 ══\n"
            f"你凝聚龙血，发动【龙血冲击】，目标【{target}】！\n"
            f"扳机落下，膛火喷涌——结果是【{display_bullet(bullet)}】！\n"
        )
        if next_live_msg:
            text += next_live_msg

        # 审判：若被审判言灵压制，枪口会强制指向自己
        if game[cur_p].get("judgement", False):
            game[cur_p]["judgement"] = False
            if target == "对方":
                target = "自己"
                text += "【审判】的言灵压制着你，枪口不受控制地转向自己！\n"

        if bullet == "实弹":
            damage = 2 if game["double"] else 1
            damage += game[cur_p].get("powerUp", 0)  # 怒焰：本回合伤害+1
            if cur_p == "player2":
                damage += game.get("bossPower", 0)  # 组队讨伐：人数越多 Boss 伤害越高
            # 炽日压制：若开枪者被压制，本次伤害至少减伤1
            if game[cur_p].get("weaken", False):
                game[cur_p]["weaken"] = False
                old_damage = damage
                damage = max(0, damage - max(1, damage // 2))
                text += f"但你的龙炎被炽日压制，伤害从 {old_damage} 降至 {damage}！"
            if target == "自己":
                if game[cur_p].get("lifeSteal", False):
                    # 血鳞：免疫伤害并恢复等量生命
                    game[cur_p]["lifeSteal"] = False
                    max_hp = self.get_mode_config(game.get("mode", "标准"))["hp"]
                    heal = min(damage, max_hp - game[cur_p]["hp"])
                    game[cur_p]["hp"] += heal
                    text += f"\n🩸 血鳞覆盖全身，龙炎被尽数吸收——免疫了 {damage} 点伤害" + (f"，恢复 {heal} 点生命！" if heal else "（生命已满）！")
                else:
                    game[cur_p]["hp"] -= damage
                    text += f"龙炎反噬己身，你损失了 {damage} 点生命！"
                    if game[cur_p]["hp"] <= 0:
                        if game[cur_p].get("nextRevive", False):
                            # 蜕生：死亡边缘复活
                            game[cur_p]["nextRevive"] = False
                            game[cur_p]["hp"] = 2
                            text += "\n🐣 蜕生发动！你于死亡边缘重燃龙血，以 2 点生命复活！"
                        elif game.get("team_hunt"):
                            # 组队讨伐：当前队员倒下，由下一位队员接替；全灭才失败
                            text += f"\n💀 {game[cur_p]['name']} 倒下了！"
                            yield event.plain_result(text)
                            if self._remove_team_member(game):
                                yield event.plain_result(f"⛑ 讨伐队仍有成员存活，{game['player1']['name']} 接替行动！")
                            else:
                                if os.path.exists(res_path("result_lose.png")):
                                    yield event.image_result(res_path("result_lose.png"))
                                lines = self.game_over(cid, winner=oth_p, loser="player1")
                                for ln in lines:
                                    yield event.plain_result(ln)
                            return
                        else:
                            yield event.plain_result(text)
                            if os.path.exists(res_path("result_lose.png")):
                                yield event.image_result(res_path("result_lose.png"))
                            lines = self.game_over(cid, winner=oth_p, loser=cur_p)
                            for ln in lines:
                                yield event.plain_result(ln)
                            return
            else:
                if game[oth_p].get("shield", False):
                    text += "但对方的青铜御座闪耀，将龙炎全部吸收！"
                    game[oth_p]["shield"] = False
                elif game[oth_p].get("goldenEye", False):
                    # 黄金瞳：免疫并全额反弹给攻击者
                    game[oth_p]["goldenEye"] = False
                    game[cur_p]["hp"] -= damage
                    text += f"黄金瞳洞悉了你的攻击！伤害被看穿并全额反弹——你反而损失了 {damage} 点生命！"
                    if game[cur_p]["hp"] <= 0:
                        if game[cur_p].get("nextRevive", False):
                            # 蜕生：死亡边缘复活
                            game[cur_p]["nextRevive"] = False
                            game[cur_p]["hp"] = 2
                            text += "\n🐣 蜕生发动！你于死亡边缘重燃龙血，以 2 点生命复活！"
                        elif game.get("team_hunt"):
                            text += f"\n💀 {game[cur_p]['name']} 倒下了！"
                            yield event.plain_result(text)
                            if self._remove_team_member(game):
                                yield event.plain_result(f"⛑ 讨伐队仍有成员存活，{game['player1']['name']} 接替行动！")
                            else:
                                if os.path.exists(res_path("result_lose.png")):
                                    yield event.image_result(res_path("result_lose.png"))
                                lines = self.game_over(cid, winner=oth_p, loser="player1")
                                for ln in lines:
                                    yield event.plain_result(ln)
                            return
                        else:
                            yield event.plain_result(text)
                            if os.path.exists(res_path("result_lose.png")):
                                yield event.image_result(res_path("result_lose.png"))
                            lines = self.game_over(cid, winner=oth_p, loser=cur_p)
                            for ln in lines:
                                yield event.plain_result(ln)
                            return
                elif game[oth_p].get("lifeSteal", False):
                    # 血鳞：免疫伤害并恢复等量生命
                    game[oth_p]["lifeSteal"] = False
                    max_hp = self.get_mode_config(game.get("mode", "标准"))["hp"]
                    heal = min(damage, max_hp - game[oth_p]["hp"])
                    game[oth_p]["hp"] += heal
                    text += f"\n🩸 对方血鳞覆盖全身，龙炎被尽数吸收——免疫了 {damage} 点伤害" + (f"，恢复 {heal} 点生命！" if heal else "（生命已满）！")
                else:
                    game[oth_p]["hp"] -= damage
                    text += f"龙炎贯穿对方，损失了 {damage} 点生命！"
                    if game[oth_p]["hp"] <= 0:
                        if game[oth_p].get("nextRevive", False):
                            # 蜕生：死亡边缘复活
                            game[oth_p]["nextRevive"] = False
                            game[oth_p]["hp"] = 2
                            text += "\n🐣 蜕生发动！对方于死亡边缘重燃龙血，以 2 点生命复活！"
                        elif game.get("team_hunt") and oth_p == "player1":
                            # Boss 击倒了当前队员
                            text += f"\n💀 {game[oth_p]['name']} 倒下了！"
                            yield event.plain_result(text)
                            if self._remove_team_member(game):
                                yield event.plain_result(f"⛑ 讨伐队仍有成员存活，{game['player1']['name']} 接替行动！")
                            else:
                                if os.path.exists(res_path("result_lose.png")):
                                    yield event.image_result(res_path("result_lose.png"))
                                lines = self.game_over(cid, winner=cur_p, loser="player1")
                                for ln in lines:
                                    yield event.plain_result(ln)
                            return
                        else:
                            yield event.plain_result(text)
                            if os.path.exists(res_path("result_win.png")):
                                yield event.image_result(res_path("result_win.png"))
                            lines = self.game_over(cid, winner=cur_p, loser=oth_p)
                            for ln in lines:
                                yield event.plain_result(ln)
                            return

        # 回合切换判定
        switch_turn = True
        if bullet == "空包弹" and target == "自己":
            text += "\n空包弹的虚光散尽，你仍保有行动权！"
            if len(game[cur_p]["items"]) < ITEM_CAP:
                bonus = random.choice(self.item_names)
                game[cur_p]["items"].append(bonus)
                text += f"\n✨ 吞枪成功，虚光反哺龙血，你额外获得言灵【{bonus}】！"
            else:
                text += "\n（背包已满，无法获得额外言灵）"
            switch_turn = False
        else:
            if game[oth_p].get("handcuff", False):
                game[oth_p]["handcuff"] = False
                text += "\n对方被王权压制，无法反击，你继续掌控全局！"
                switch_turn = False
            elif game[cur_p].get("timeZero", False):
                game[cur_p]["timeZero"] = False
                text += "\n时间零发动！你冻结了时间，继续行动！"
                switch_turn = False
            else:
                if game.get("team_hunt"):
                    if game["currentTurn"] == 1:
                        # 队员轮流行动，全部行动完才轮到 Boss
                        game["team_index"] = game.get("team_index", 0) + 1
                        if game["team_index"] < len(game["team_members"]):
                            game["player1"] = game["team_members"][game["team_index"]]
                            game["currentTurn"] = 1
                            new_p = "player1"
                            game[new_p]["drawCount"] = 0
                            text += f"\n切换队员：现在由 {self.at_id(game[new_p]['name'])} 行动！"
                        else:
                            game["team_index"] = 0
                            game["currentTurn"] = 2
                            new_p = "player2"
                            game[new_p]["drawCount"] = 0
                            text += f"\n全体队员行动完毕，【{game[new_p]['name']}】开始反击！"
                    else:
                        game["team_index"] = 0
                        game["player1"] = game["team_members"][0]
                        game["currentTurn"] = 1
                        new_p = "player1"
                        game[new_p]["drawCount"] = 0
                        text += f"\n切换回合：现在由 {self.at_id(game[new_p]['name'])} 决定下一步！"
                else:
                    game["currentTurn"] = 1 if game["currentTurn"] == 2 else 2
                    new_p = f"player{game['currentTurn']}"
                    game[new_p]["drawCount"] = 0
                    text += f"\n切换回合：现在由 {self.at_id(game[new_p]['name'])} 决定下一步！"
                game["usedHandcuff"] = False

        # 时间零只要发动过就消耗（即使空包弹/王权已保留行动权，也不会叠加）
        if game[cur_p].get("timeZero", False):
            game[cur_p]["timeZero"] = False

        yield event.plain_result(text)
        game["double"] = False
        game[cur_p]["powerUp"] = 0  # 怒焰：无论是否打出实弹，本回合强化消耗
        # 屠龙局：轮到 Boss 时自动行动
        if game.get("boss") and game["currentTurn"] == 2 and cid in self.games:
            asyncio.create_task(self._boss_turn(cid))
        if len(game["bullet"]) == 0:
            yield event.plain_result(self.next_round(game))

    def next_round(self, game: dict):
        """
        进入下一轮：重新生成弹夹，并为双方发放少量随机言灵。
        """
        game["round"] += 1
        mode = game.get("mode", "标准")
        cfg = self.get_mode_config(mode)
        game["bullet"] = generate_random_bullet_list(cfg["bullet_min"], cfg["bullet_max"])
        bullet_list = game["bullet"]
        item_pool = list(self.item_list.keys())
        item_count = game.get("roundItems", cfg["round_items"])
        if game.get("team_hunt"):
            # 组队讨伐：每位队员和 Boss 都获得新言灵
            for m in game["team_members"]:
                for _ in range(item_count):
                    if len(m["items"]) < ITEM_CAP:
                        m["items"].append(random.choice(item_pool))
                m["items"] = m["items"][:8]
            boss = game["player2"]
            for _ in range(item_count):
                if len(boss["items"]) < ITEM_CAP:
                    boss["items"].append(random.choice(item_pool))
            boss["items"] = boss["items"][:8]
        else:
            cur_p = f"player{game['currentTurn']}"
            oth_p = f"player{1 if game['currentTurn'] == 2 else 2}"
            for _ in range(item_count):
                game[cur_p]["items"].append(random.choice(item_pool))
                game[oth_p]["items"].append(random.choice(item_pool))
            game["player1"]["items"] = game["player1"]["items"][:8]
            game["player2"]["items"] = game["player2"]["items"][:8]

        # 清除回合性负面状态
        game["double"] = False
        game["usedHandcuff"] = False
        if game.get("team_hunt"):
            reset_players = list(game["team_members"]) + [game["player2"]]
        else:
            reset_players = [game["player1"], game["player2"]]
        for p in reset_players:
            p["handcuff"] = False
            p["judgement"] = False
            p["timeZero"] = False
            p["weaken"] = False
            p["silenced"] = False
            p["nextLive"] = False
            p["hypnotized"] = False
            p["noDraw"] = False      # 血脉诅咒：轮末解除
            p["powerUp"] = 0         # 怒焰：回合性增益，轮末清除
            # 血鳞/黄金瞳为一次性触发状态（与护盾相同），跨轮保留直至触发
            p["drawCount"] = 0
            p["drawn"] = False
            p["usedItems"] = 0  # 每轮重置 PvP 言灵使用次数
            # 保底进度与蜕生（复活机会）跨轮保留，提升长期博弈价值
        if game.get("team_hunt"):
            game["team_index"] = 0
            game["player1"] = game["team_members"][0]
            game["currentTurn"] = 1

        live_count = self.count_bullet(bullet_list, "实弹")
        blank_count = len(bullet_list) - live_count
        msg = textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            弹夹打空，进入第 {game["round"]} 轮！
            炼金手枪重新装填 {len(bullet_list)} 发弹：
            🔥 龙炎弹 {live_count} 发 ｜ 💨 空包弹 {blank_count} 发
            全员各获得 {item_count} 个随机言灵（上限 8）。
            回合内仍可发送“抽”消耗生命补充言灵。
        """)
        return msg

    async def use_item(self, cid: str, item: str, event: AstrMessageEvent):
        """
        施展言灵：先咏唱，再调用对应言灵效果。
        施展前先移除言灵：避免“复制/偷取类言灵”把刚用掉的卡又复制回来（净赚一张）。
        """
        game = self.games[cid]
        cur_p = f"player{game['currentTurn']}"
        # PvP 模式每轮每名玩家最多使用 3 次言灵；屠龙/组队讨伐不受此限制
        if not game.get("boss"):
            if game[cur_p].get("usedItems", 0) >= PVP_MAX_ITEMS_PER_ROUND:
                yield event.plain_result(f"🔮 你本回合/本轮已经使用过 {PVP_MAX_ITEMS_PER_ROUND} 次言灵，无法继续咏唱。")
                return
            game[cur_p]["usedItems"] = game[cur_p].get("usedItems", 0) + 1
        chant = self.item_list[item]["chant"]
        yield event.plain_result(f"你开始咏唱【{item}】……\n「{chant}」")
        if item in game[cur_p]["items"]:
            game[cur_p]["items"].remove(item)
        lines = await self.item_list[item]["use"](self, cid, cur_p, None, event)
        for ln in lines:
            yield event.plain_result(ln)
        self._touch(cid)
        if cid in self.games:
            yield event.plain_result(f"【{item}】的力量渐渐沉寂，但它的传说已刻入你的血脉。")

    # ================= 攻击系言灵 =================
    @staticmethod
    async def use_junyan(plugin, cid, cur_player, pick, event):
        """言灵·君焰：下一发造成双倍伤害"""
        g = plugin.games[cid]
        g["double"] = True
        return [
            "炽热龙炎自血脉中升腾……",
            "炼金手枪的枪管被烧得通红，下一发龙炎弹伤害翻倍！"
        ]

    @staticmethod
    async def use_leichi(plugin, cid, cur_player, pick, event):
        """言灵·雷池：对对手造成1点伤害，并随机丢弃对方一个言灵"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["雷池轰然落下，雷光四射……"]
        msgs, finished, shielded = plugin.resolve_damage(cid, g, oth_p, 1, msgs)
        if finished:
            return msgs
        if not shielded:
            if g[oth_p]["items"]:
                lost = random.choice(g[oth_p]["items"])
                g[oth_p]["items"].remove(lost)
                msgs.append(f"雷光击碎了对方的言灵印记，【{lost}】被丢弃！")
            else:
                msgs.append("对方手中已无言灵可被雷池击碎。")
        return msgs

    @staticmethod
    async def use_shenpan(plugin, cid, cur_player, pick, event):
        """言灵·审判：对方下一次龙血冲击强制指向自己，且你下一发伤害翻倍"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["judgement"] = True
        g["double"] = True
        return [
            "审判的钟声在对方头顶响起，罪与罚同时降临！",
            f"对方下一次龙血冲击时，枪口将被迫指向自己；你下一发龙炎弹伤害翻倍！"
        ]

    @staticmethod
    async def use_zhulong(plugin, cid, cur_player, pick, event):
        """言灵·烛龙：下一发子弹必定变为龙炎弹，且造成双倍伤害"""
        g = plugin.games[cid]
        g[cur_player]["nextLive"] = True
        g["double"] = True
        return [
            "烛龙之瞳缓缓睁开，昼夜为之逆转……",
            "下一发子弹必定化为龙炎弹，且伤害翻倍！"
        ]

    @staticmethod
    async def use_heiyanlaoyu(plugin, cid, cur_player, pick, event):
        """言灵·黑炎牢狱：1点伤害+炽日压制"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["黑炎牢狱困住对方，灼烧血脉……"]
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 1, msgs)
        if finished:
            return msgs
        g[oth_p]["weaken"] = True
        msgs.append("炽日压制已悄然缠绕对方！")
        return msgs

    @staticmethod
    async def use_cangleizhipei(plugin, cid, cur_player, pick, event):
        """言灵·苍雷支配：对对手造成3点伤害"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["苍雷支配轰然降临，雷光撕裂长空！"]
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 3, msgs)
        return msgs

    @staticmethod
    async def use_shenxue(plugin, cid, cur_player, pick, event):
        """言灵·深血：对对手造成1点伤害"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["深血如毒蛇般钻入对方血脉……"]
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 1, msgs)
        return msgs

    @staticmethod
    async def use_chiri(plugin, cid, cur_player, pick, event):
        """言灵·炽日：令对方下一次龙血冲击伤害减半（至少减伤1）"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["weaken"] = True
        return [
            "炽日凌空，强光刺入对方双眼……",
            "对方下一次龙血冲击的伤害将减半（至少减伤1）！"
        ]

    # ================= 防御系言灵 =================
    @staticmethod
    async def use_wuchen(plugin, cid, cur_player, pick, event):
        """言灵·无尘之地：卸下当前膛内的一发子弹"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["无尘之地展开，但枪膛已空。"]
        bullet = g["bullet"].pop()
        msg = [
            "无尘领域瞬间荡开，连子弹都被斥离……",
            f"“咔哒”一声，一发【{display_bullet(bullet)}】被剥离枪膛！"
        ]
        if len(g["bullet"]) == 0:
            msg.append(plugin.next_round(g))
        return msg

    @staticmethod
    async def use_shengcai(plugin, cid, cur_player, pick, event):
        """言灵·圣裁：恢复1点生命值"""
        g = plugin.games[cid]
        max_hp = plugin.get_mode_config(g.get("mode", "标准"))["hp"]
        if g[cur_player]["hp"] < max_hp:
            g[cur_player]["hp"] += 1
            return [
                "圣裁的辉光自天而降……",
                "血脉中的创伤缓缓愈合，恢复了 1 点生命！"
            ]
        else:
            return [
                "圣裁的辉光照耀，但你已满血，",
                "不过这也让你感到一阵安心。"
            ]

    @staticmethod
    async def use_qingtong(plugin, cid, cur_player, pick, event):
        """言灵·青铜御座：获得护盾"""
        g = plugin.games[cid]
        g[cur_player]["shield"] = True
        return ["青铜御座拔地而起，你被青铜色领域笼罩，下一次攻击将被抵消！"]

    @staticmethod
    async def use_buxiu(plugin, cid, cur_player, pick, event):
        """言灵·不朽：恢复3点生命，并清除所有负面状态"""
        g = plugin.games[cid]
        max_hp = plugin.get_mode_config(g.get("mode", "标准"))["hp"]
        g[cur_player]["hp"] = min(max_hp, g[cur_player]["hp"] + 3)
        g[cur_player]["handcuff"] = False
        g[cur_player]["judgement"] = False
        g[cur_player]["timeZero"] = False
        g[cur_player]["weaken"] = False
        g[cur_player]["silenced"] = False
        g[cur_player]["hypnotized"] = False
        g[cur_player]["noDraw"] = False
        return [
            "不朽的金色辉光笼罩着你，仿佛时间也无法侵蚀……",
            "恢复了 3 点生命，并清除了所有负面状态！"
        ]

    @staticmethod
    async def use_wangzhishi(plugin, cid, cur_player, pick, event):
        """言灵·王之侍：无护盾则获得护盾；已有护盾则恢复1点生命"""
        g = plugin.games[cid]
        max_hp = plugin.get_mode_config(g.get("mode", "标准"))["hp"]
        if not g[cur_player].get("shield", False):
            g[cur_player]["shield"] = True
            return ["王之侍的虚影在你身前浮现，护盾已展开！"]
        elif g[cur_player]["hp"] < max_hp:
            g[cur_player]["hp"] += 1
            return ["王之侍的力量涌入伤口，恢复了 1 点生命！"]
        else:
            new_item = random.choice(list(plugin.item_list.keys()))
            g[cur_player]["items"].append(new_item)
            return [f"王之侍之力满溢而出，额外获得言灵【{new_item}】！"]

    @staticmethod
    async def use_guiisheng(plugin, cid, cur_player, pick, event):
        """言灵·鬼胜：恢复2点生命，但随机丢弃一个自己的言灵"""
        g = plugin.games[cid]
        max_hp = plugin.get_mode_config(g.get("mode", "标准"))["hp"]
        recover = min(max_hp - g[cur_player]["hp"], 2)
        g[cur_player]["hp"] += recover
        msgs = [
            "鬼胜附体，痛觉与创伤一并被压制……",
            f"恢复了 {recover} 点生命！"
        ]
        if g[cur_player]["items"]:
            lost = random.choice(g[cur_player]["items"])
            g[cur_player]["items"].remove(lost)
            msgs.append(f"但代价随之而来，你遗忘了【{lost}】！")
        return msgs

    @staticmethod
    async def use_heiri(plugin, cid, cur_player, pick, event):
        """言灵·黑日：恢复2点生命并获得护盾"""
        g = plugin.games[cid]
        max_hp = plugin.get_mode_config(g.get("mode", "标准"))["hp"]
        recover = min(max_hp - g[cur_player]["hp"], 2)
        g[cur_player]["hp"] += recover
        g[cur_player]["shield"] = True
        return [
            "黑日当空，万物在阴影中重获新生……",
            f"恢复了 {recover} 点生命，并获得青铜御座护盾！"
        ]

    # ================= 辅助系言灵 =================
    @staticmethod
    async def use_jingtong(plugin, cid, cur_player, pick, event):
        """言灵·镜瞳：复制对方一个随机言灵，并免费获得一个随机言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if len(g[cur_player]["items"]) >= 8:
            return ["黄金瞳中万千符文流转……但你的言灵背包已满，无法再承载更多言灵。"]
        msgs = ["黄金瞳中万千符文流转……"]
        if g[oth_p]["items"]:
            copied = random.choice(g[oth_p]["items"])
            g[cur_player]["items"].append(copied)
            msgs.append(f"镜瞳映出对方血脉中的言灵印记，你复制了【{copied}】！")
        else:
            msgs.append("对方手中没有任何言灵可以复制，但镜瞳仍在运转……")
        if len(g[cur_player]["items"]) < 8:
            free_item = random.choice(list(plugin.item_list.keys()))
            g[cur_player]["items"].append(free_item)
            msgs.append(f"镜瞳解析万象，额外为你凝聚了【{free_item}】！")
        return msgs

    @staticmethod
    async def use_fengwang(plugin, cid, cur_player, pick, event):
        """言灵·风王之瞳：查看当前膛内的子弹（私发告知）"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["风王之瞳扫过枪膛，却发现其中已无子弹。"]
        bullet_type = g["bullet"][-1]
        info = f"风之瞳在虚空中睁开……你清晰地看见下一发是【{display_bullet(bullet_type)}】！"
        if await plugin._private_send(event, f"══ 🐉 龙族轮盘 ══\n{info}"):
            return ["风之瞳在虚空中睁开，枪膛的真相已私发给你！"]
        return [info]  # 私发失败时回退群播

    @staticmethod
    async def use_xianzhi(plugin, cid, cur_player, pick, event):
        """言灵·先知：随机告知枪膛中某发子弹的类型（私发告知）"""
        g = plugin.games[cid]
        bullet_count = len(g["bullet"])
        if bullet_count == 0:
            return ["先知低语片刻，却发现枪膛中空空如也……"]
        idx = random.randint(0, bullet_count - 1)
        firing_order = bullet_count - idx
        bullet_type = g["bullet"][idx]
        info = f"先知的虚影在你耳边低语：“第 {firing_order} 发，是【{display_bullet(bullet_type)}】。”"
        if await plugin._private_send(event, f"══ 🐉 龙族轮盘 ══\n{info}"):
            return ["先知低语片刻，预言的真相已私发给你！"]
        return [info]  # 私发失败时回退群播

    @staticmethod
    async def use_lianyou(plugin, cid, cur_player, pick, event):
        """言灵·镰鼬：偷走对方背包中的随机一个言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if not g[oth_p]["items"]:
            return ["镰鼬呼啸而过，但对方手中没有任何言灵。"]
        stolen = random.choice(g[oth_p]["items"])
        g[oth_p]["items"].remove(stolen)
        g[cur_player]["items"].append(stolen)
        return [
            "镰鼬化作一道残影掠过对方……",
            f"你成功偷走了对方的【{stolen}】！"
        ]

    @staticmethod
    async def use_she(plugin, cid, cur_player, pick, event):
        """言灵·蛇：随机丢弃对方一个言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if not g[oth_p]["items"]:
            return ["蛇瞳扫过对方，但对方手中没有任何言灵可吞噬。"]
        lost = random.choice(g[oth_p]["items"])
        g[oth_p]["items"].remove(lost)
        return [
            "蛇瞳在虚空中亮起，一道毒影咬碎了对方的言灵印记……",
            f"对方遗忘了【{lost}】！"
        ]

    @staticmethod
    async def use_xuexijieluo(plugin, cid, cur_player, pick, event):
        """言灵·血系结罗：双方各获得一个随机言灵"""
        g = plugin.games[cid]
        msgs = ["血系结罗展开，双方血脉中的言灵被重新牵动……"]
        for p in ["player1", "player2"]:
            if len(g[p]["items"]) >= 8:
                msgs.append(f"{plugin.at_id(g[p]['name'])} 的背包已满，无法获得新言灵。")
            else:
                new_item = random.choice(list(plugin.item_list.keys()))
                g[p]["items"].append(new_item)
                msgs.append(f"{plugin.at_id(g[p]['name'])} 获得了【{new_item}】！")
        return msgs

    @staticmethod
    async def use_tianyan(plugin, cid, cur_player, pick, event):
        """言灵·天演：免费抽取一张随机言灵"""
        g = plugin.games[cid]
        if len(g[cur_player]["items"]) >= 8:
            return ["天演推演完毕，但你的言灵背包已满，无法获得新言灵。"]
        new_item = random.choice(list(plugin.item_list.keys()))
        g[cur_player]["items"].append(new_item)
        return [
            "天演万象，命运轨迹在眼中展开……",
            f"你免费获得了言灵【{new_item}】！"
        ]

    @staticmethod
    async def use_chana(plugin, cid, cur_player, pick, event):
        """言灵·刹那：重置本回合抽卡费用"""
        g = plugin.games[cid]
        g[cur_player]["drawCount"] = 0
        return [
            "刹那之间，流光倒转……",
            "本回合抽卡费用已重置，下次抽卡重新从 2 点生命开始！"
        ]

    @staticmethod
    async def use_xuemaiqianyin(plugin, cid, cur_player, pick, event):
        """言灵·血脉牵引：与对方随机交换一个言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if not g[cur_player]["items"] or not g[oth_p]["items"]:
            return ["血脉牵引需要双方各持有一个言灵才能缔结，当前无法交换。"]
        my_item = random.choice(g[cur_player]["items"])
        oth_item = random.choice(g[oth_p]["items"])
        g[cur_player]["items"].remove(my_item)
        g[oth_p]["items"].remove(oth_item)
        g[cur_player]["items"].append(oth_item)
        g[oth_p]["items"].append(my_item)
        return [
            "血脉为引，两道言灵印记在虚空中交换……",
            f"你获得了【{oth_item}】，对方获得了【{my_item}】！"
        ]

    @staticmethod
    async def use_shenyu(plugin, cid, cur_player, pick, event):
        """言灵·神谕：查看弹夹顺序（私发），下一发变空包弹，并获得一次额外行动权"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["神谕降下，但枪膛中已无子弹。"]
        order = " → ".join(display_bullet(b) for b in reversed(g["bullet"]))
        g["bullet"][-1] = "空包弹"
        g[cur_player]["timeZero"] = True
        info = f"神谕的虚影在你眼前展开未来——当前弹夹顺序（第一发在前）：{order}"
        if await plugin._private_send(event, f"══ 🐉 龙族轮盘 ══\n{info}"):
            return [
                "神谕降下，命运的轨迹已私发给你！",
                "神谕改写因果，下一发已被替换为【空包弹】！",
                "时间仿佛被神谕拨动，你下一次龙血冲击后仍可继续行动！"
            ]
        return [  # 私发失败时回退群播
            "神谕的虚影在你眼前展开未来……",
            f"当前弹夹顺序（第一发在前）：{order}",
            "神谕改写因果，下一发已被替换为【空包弹】！",
            "时间仿佛被神谕拨动，你下一次龙血冲击后仍可继续行动！"
        ]

    # ================= 特殊系言灵 =================
    @staticmethod
    async def use_wangquan(plugin, cid, cur_player, pick, event):
        """言灵·王权：让对方跳过下一回合"""
        g = plugin.games[cid]
        if g.get("usedHandcuff", False):
            return ["王权的威压已在本回合施展，无法再次束缚对手。"]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["handcuff"] = True
        g["usedHandcuff"] = True
        return [
            "你以王权之名下达律令……",
            "对方被无形的威压钉在原地，下一回合将被迫放弃行动！"
        ]

    @staticmethod
    async def use_mingzhao(plugin, cid, cur_player, pick, event):
        """言灵·冥照：将当前膛内最后一发子弹反转"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["冥照亮起，却发现枪膛中无子弹可逆转。"]
        old_bullet = g["bullet"].pop()
        new_bullet = "空包弹" if old_bullet == "实弹" else "实弹"
        g["bullet"].append(new_bullet)
        return [
            "冥照的黑暗将子弹吞没……",
            f"原本的【{display_bullet(old_bullet)}】瞬间变为【{display_bullet(new_bullet)}】！"
        ]

    @staticmethod
    async def use_shijianling(plugin, cid, cur_player, pick, event):
        """言灵·时间零：下一次开枪后仍保留行动权"""
        g = plugin.games[cid]
        g[cur_player]["timeZero"] = True
        return [
            "世界在你眼中慢了下来，时间如琥珀般凝固……",
            "下一次龙血冲击后，你仍能继续行动！"
        ]

    @staticmethod
    async def use_wo(plugin, cid, cur_player, pick, event):
        """言灵·涡：重新洗牌当前弹夹"""
        g = plugin.games[cid]
        if len(g["bullet"]) <= 1:
            return ["涡的力量卷过枪膛，但子弹太少，洗了个寂寞。"]
        random.shuffle(g["bullet"])
        live_count = plugin.count_bullet(g["bullet"], "实弹")
        blank_count = len(g["bullet"]) - live_count
        return [
            "涡之领域将弹夹吞入旋流，因果被重新编织……",
            f"弹夹已重新洗牌：🔥 龙炎弹 {live_count} 发 ｜ 💨 空包弹 {blank_count} 发。"
        ]

    @staticmethod
    async def use_dong(plugin, cid, cur_player, pick, event):
        """言灵·冬：将当前膛内最后一发子弹变为空包弹"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["冬的寒气扫过枪膛，却发现其中已无子弹。"]
        old_bullet = g["bullet"][-1]
        g["bullet"][-1] = "空包弹"
        return [
            "凛冬降临，枪膛内的火焰也被冻结……",
            f"原本的【{display_bullet(old_bullet)}】被冻成了一发【空包弹】！"
        ]

    @staticmethod
    async def use_mengpo(plugin, cid, cur_player, pick, event):
        """言灵·梦貘：随机丢弃对方背包中的两个言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if not g[oth_p]["items"]:
            return ["梦貘侵入梦境，但对方手中没有任何言灵。"]
        msgs = ["梦貘潜入对方的梦境，言灵印记开始剥落……"]
        for _ in range(2):
            if not g[oth_p]["items"]:
                break
            lost = random.choice(g[oth_p]["items"])
            g[oth_p]["items"].remove(lost)
            msgs.append(f"对方遗忘了【{lost}】！")
        return msgs

    @staticmethod
    async def use_jielv(plugin, cid, cur_player, pick, event):
        """言灵·戒律：令对方下一回合无法咏唱言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["silenced"] = True
        return [
            "戒律如山，万言噤声……",
            f"对方下一回合将无法咏唱任何言灵！"
        ]

    @staticmethod
    async def use_huangdi(plugin, cid, cur_player, pick, event):
        """言灵·皇帝：彩蛋言灵，对方跳过下一回合且下一发必为龙炎弹"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["handcuff"] = True
        g["usedHandcuff"] = True
        g[cur_player]["nextLive"] = True
        return [
            "皇帝临世，龙血为之臣服，天地为之噤声！",
            "对方下一回合无法行动，且你下一发子弹必定化为龙炎弹！"
        ]

    @staticmethod
    async def use_gui_xu(plugin, cid, cur_player, pick, event):
        """言灵·归墟：将当前弹夹中所有龙炎弹变为空包弹"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["归墟席卷枪膛，但其中已无子弹。"]
        live_count = plugin.count_bullet(g["bullet"], "实弹")
        g["bullet"] = ["空包弹"] * len(g["bullet"])
        return [
            "万流归墟，一切终末降临……",
            f"枪膛中的 {live_count} 发龙炎弹全部被吞没为空包弹！"
        ]

    # ================= 新增扩充言灵 =================
    @staticmethod
    async def use_laiyin(plugin, cid, cur_player, pick, event):
        """言灵·莱茵：对对方造成3点伤害，自己也损失1点"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["莱茵之力在枪口凝聚，核火焚天！"]
        # 自身反噬（护盾无法抵消）
        g[cur_player]["hp"] -= 1
        msgs.append("你自己也承受了 1 点反噬。")
        if g[cur_player]["hp"] <= 0:
            msgs.append(f"{plugin.at_id(g[cur_player]['name'])} 被莱茵反噬吞噬！")
            msgs.extend(plugin.game_over(cid, winner=oth_p, loser=cur_player))
            return msgs
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 3, msgs)
        return msgs

    @staticmethod
    async def use_shishiyewu(plugin, cid, cur_player, pick, event):
        """言灵·湿婆业舞：双方各损失1点生命，并各随机丢弃一个言灵"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["湿婆起舞，业火焚世，众生皆为灰烬！"]
        g[cur_player]["hp"] -= 1
        g[oth_p]["hp"] -= 1
        msgs.append("双方各损失 1 点生命！")
        for p in (cur_player, oth_p):
            if g[p]["items"]:
                lost = random.choice(g[p]["items"])
                g[p]["items"].remove(lost)
                msgs.append(f"{plugin.at_id(g[p]['name'])} 遗忘了【{lost}】！")
        # 处理死亡（先判断对方再判断自己）
        if g[oth_p]["hp"] <= 0:
            if g.get("team_hunt") and oth_p == "player1":
                msgs.append(f"{plugin.at_id(g[oth_p]['name'])} 倒下了！")
                if plugin._remove_team_member(g):
                    msgs.append(f"⛑ 讨伐队仍有成员存活，{g['player1']['name']} 接替行动！")
                else:
                    msgs.append(f"{plugin.at_id(g[cur_player]['name'])} 获得了最终胜利！")
                    msgs.extend(plugin.game_over(cid, winner=cur_player, loser="player1"))
                return msgs
            msgs.append(f"{plugin.at_id(g[oth_p]['name'])} 倒下了！")
            msgs.append(f"{plugin.at_id(g[cur_player]['name'])} 获得了最终胜利！")
            msgs.extend(plugin.game_over(cid, winner=cur_player, loser=oth_p))
            return msgs
        if g[cur_player]["hp"] <= 0:
            if g.get("team_hunt") and cur_player == "player1":
                msgs.append(f"{plugin.at_id(g[cur_player]['name'])} 也倒下了！")
                if plugin._remove_team_member(g):
                    msgs.append(f"⛑ 讨伐队仍有成员存活，{g['player1']['name']} 接替行动！")
                else:
                    msgs.append(f"{plugin.at_id(g[oth_p]['name'])} 获得了最终胜利！")
                    msgs.extend(plugin.game_over(cid, winner=oth_p, loser="player1"))
                return msgs
            msgs.append(f"{plugin.at_id(g[cur_player]['name'])} 也倒下了！")
            msgs.append(f"{plugin.at_id(g[oth_p]['name'])} 获得了最终胜利！")
            msgs.extend(plugin.game_over(cid, winner=oth_p, loser=cur_player))
            return msgs
        return msgs

    @staticmethod
    async def use_yaoshi(plugin, cid, cur_player, pick, event):
        """言灵·钥匙：查看对方所有言灵，并复制其中一个"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        if not g[oth_p]["items"]:
            return ["钥匙插入虚空，但对方手中没有任何言灵可以打开。"]
        if len(g[cur_player]["items"]) >= 8:
            return ["钥匙打开了对方的言灵之锁，但你的背包已满，无法复制。"]
        items = "、".join(g[oth_p]["items"])
        copied = random.choice(g[oth_p]["items"])
        g[cur_player]["items"].append(copied)
        return [
            f"钥匙开启了对方的言灵之锁：{items}",
            f"你复制了【{copied}】！"
        ]

    @staticmethod
    async def use_cuimian(plugin, cid, cur_player, pick, event):
        """言灵·催眠：令对方下一回合无法发动龙血冲击"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        g[oth_p]["hypnotized"] = True
        return [
            "催眠之眼在虚空中睁开，对方意识渐渐模糊……",
            "对方下一回合将无法发动龙血冲击！"
        ]

    @staticmethod
    async def use_yinliu(plugin, cid, cur_player, pick, event):
        """言灵·阴流：查看当前膛内子弹（私发告知）并将其卸下"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["阴流掠过枪膛，却发现其中已无子弹。"]
        bullet = g["bullet"].pop()
        msgs = [
            "阴流无声，风刃悄然探入枪膛……",
            f"你卸下了一发子弹！"
        ]
        info = f"被你卸下的那发是【{display_bullet(bullet)}】。"
        if await plugin._private_send(event, f"══ 🐉 龙族轮盘 ══\n{info}"):
            msgs.append("它的真身，已私发给你。")
        else:
            msgs.append(info)  # 私发失败时回退群播
        if len(g["bullet"]) == 0:
            msgs.append(plugin.next_round(g))
        return msgs

    # ================= 继续扩充的言灵 =================
    @staticmethod
    async def use_xixuelian(plugin, cid, cur_player, pick, event):
        """言灵·吸血镰：对对方造成1点伤害，并偷走对方一个随机言灵"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["吸血镰呼啸而至，风刃噬魂！"]
        msgs, finished, shielded = plugin.resolve_damage(cid, g, oth_p, 1, msgs)
        if finished:
            return msgs
        if not shielded:
            if g[oth_p]["items"]:
                stolen = random.choice(g[oth_p]["items"])
                g[oth_p]["items"].remove(stolen)
                if len(g[cur_player]["items"]) < ITEM_CAP:
                    g[cur_player]["items"].append(stolen)
                    msgs.append(f"吸血镰卷走了对方的【{stolen}】！")
                else:
                    msgs.append(f"吸血镰卷走了对方的【{stolen}】，但你的背包已满，它消散于风中。")
            else:
                msgs.append("对方手中没有言灵可被吸血镰夺走。")
        return msgs

    @staticmethod
    async def use_bayi(plugin, cid, cur_player, pick, event):
        """言灵·八岐：随机丢弃对方两个言灵，并令对方下一回合无法咏唱言灵"""
        g = plugin.games[cid]
        oth_p = "player2" if cur_player == "player1" else "player1"
        msgs = ["八岐之影自深渊中升起，噩梦降临！"]
        for _ in range(2):
            if not g[oth_p]["items"]:
                break
            lost = random.choice(g[oth_p]["items"])
            g[oth_p]["items"].remove(lost)
            msgs.append(f"对方遗忘了【{lost}】！")
        g[oth_p]["silenced"] = True
        msgs.append("八岐的咆哮令对方无法咏唱任何言灵！")
        return msgs

    @staticmethod
    async def use_yintuoluo(plugin, cid, cur_player, pick, event):
        """言灵·因陀罗：对对方造成3点伤害，并令对方下一回合无法发动龙血冲击"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["因陀罗之怒自苍穹劈落！"]
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 3, msgs)
        if finished:
            return msgs
        g[oth_p]["hypnotized"] = True
        msgs.append("雷帝余威令对方下一回合无法发动龙血冲击！")
        return msgs

    @staticmethod
    async def use_yinlei(plugin, cid, cur_player, pick, event):
        """言灵·阴雷：将当前膛内最后一发子弹变为龙炎弹"""
        g = plugin.games[cid]
        if not g["bullet"]:
            return ["阴雷在枪膛中暗涌，却发现其中已无子弹。"]
        old_bullet = g["bullet"][-1]
        g["bullet"][-1] = "实弹"
        return [
            "阴雷无声涌入枪膛，将沉寂化作杀机……",
            f"原本的【{display_bullet(old_bullet)}】被改写为【龙炎弹】！"
        ]

    # ================= v1.9.0 新增言灵 =================
    @staticmethod
    async def use_yianmie(plugin, cid, cur_player, pick, event):
        """言灵·湮灭：对对方造成2点伤害，并将下一发子弹变为空包弹"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        msgs = ["湮灭领域骤然展开，因果为之崩解……"]
        msgs, finished, _ = plugin.resolve_damage(cid, g, oth_p, 2, msgs)
        if finished:
            return msgs
        if g["bullet"]:
            old = g["bullet"][-1]
            g["bullet"][-1] = BULLET_BLANK
            msgs.append(f"弹夹深处传来空洞的回响，下一发【{display_bullet(old)}】被湮灭改写为【空包弹】！")
        else:
            msgs.append("湮灭席卷枪膛，但其中已无子弹可改写。")
        return msgs

    @staticmethod
    async def use_nuyan(plugin, cid, cur_player, pick, event):
        """言灵·怒焰：本回合下一次龙血冲击伤害+1"""
        g = plugin.games[cid]
        g[cur_player]["powerUp"] = g[cur_player].get("powerUp", 0) + 1
        return [
            "怒焰在血脉中沸腾，枪管被烧得滚烫……",
            "本回合下一次龙血冲击伤害 +1（可与双倍叠加）！"
        ]

    @staticmethod
    async def use_tuisheng(plugin, cid, cur_player, pick, event):
        """言灵·蜕生：本局内死亡时以2点生命复活一次"""
        g = plugin.games[cid]
        g[cur_player]["nextRevive"] = True
        return [
            "龙血在心脏深处重新奔涌，生命之火重燃……",
            "你获得了『蜕生』：本局内死亡时将以 2 点生命复活一次！"
        ]

    @staticmethod
    async def use_xuelin(plugin, cid, cur_player, pick, event):
        """言灵·血鳞：免疫下一次受到的龙血冲击伤害，并恢复等量生命"""
        g = plugin.games[cid]
        g[cur_player]["lifeSteal"] = True
        return [
            "血鳞覆盖全身，如龙甲般森然泛光……",
            "你获得了『血鳞』：下一次受到的龙血冲击伤害将免疫，并恢复等量生命！"
        ]

    @staticmethod
    async def use_huangjintong(plugin, cid, cur_player, pick, event):
        """言灵·黄金瞳：下次受到龙血冲击伤害时免疫并全额反弹给攻击者"""
        g = plugin.games[cid]
        g[cur_player]["goldenEye"] = True
        return [
            "黄金瞳洞开，世界在你眼中只剩龙血奔涌的轨迹……",
            "你获得了『黄金瞳』：下一次受到的龙血冲击伤害将免疫，并全额反弹给攻击者！"
        ]

    @staticmethod
    async def use_xuemaizuzhou(plugin, cid, cur_player, pick, event):
        """言灵·血脉诅咒：令对方下一回合无法抽取言灵"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        g[oth_p]["noDraw"] = True
        return [
            "血色的诅咒沿着对方的血脉悄然蔓延……",
            "对方下一回合将无法消耗生命抽取言灵！"
        ]

    @staticmethod
    async def use_lunhui(plugin, cid, cur_player, pick, event):
        """言灵·轮回：交换双方当前生命值"""
        g = plugin.games[cid]
        oth_p = other_player(cur_player)
        hp_me = g[cur_player]["hp"]
        hp_oth = g[oth_p]["hp"]
        g[cur_player]["hp"] = hp_oth
        g[oth_p]["hp"] = hp_me
        return [
            "轮回之轮轰然转动，命运被强行置换……",
            f"双方生命互换：你 {hp_me} → {hp_oth}，对方 {hp_oth} → {hp_me}！"
        ]

    # ------------- 游戏结束及辅助函数 -------------
    def game_over(self, cid: str, winner: str, loser: str):
        """
        宣告胜者、结算龙币与押注，并删除当前游戏数据。
        屠龙局走独立结算（奖励/击杀数，无押注）。
        """
        g = self.games[cid]
        if g.get("boss"):
            human_win = winner == "player1"
            text = textwrap.dedent(f"""\
                ══ 🐉 龙族轮盘 · 屠龙 ══
                {('龙王庞大的身躯轰然倒地，你完成了屠龙的壮举！' if human_win else f'你的龙血燃尽了……{g["player2"]["name"]} 的领域重归沉寂。')}
            """)
            settle_lines = self._settle_boss(cid, human_win)
            del self.games[cid]
            return [text] + settle_lines
        winner_name = g[winner]["name"]
        loser_name = g[loser]["name"]
        text = textwrap.dedent(f"""\
            ══ 🐉 龙族轮盘 ══
            {self.at_id(loser_name)} 的龙血燃尽了……
            {self.at_id(winner_name)} 以龙血之名获得了最终胜利！
            卡塞尔学院地下赌局正式结束，期待下次再战！
        """)
        settle_lines = self._settle(cid, winner, loser)
        del self.games[cid]
        return [text] + settle_lines

    def count_bullet(self, bullet_list, key):
        """统计列表中指定类型子弹的数量"""
        return sum(1 for b in bullet_list if b == key)

    def _remove_team_member(self, g: dict, member_key: str = "player1") -> bool:
        """
        组队讨伐中移除已倒下的当前队员。
        返回 True 表示仍有队员存活并已切换到下一位；False 表示全灭。
        """
        if not g.get("team_hunt"):
            return False
        team = g.get("team_members", [])
        idx = g.get("team_index", 0)
        mid = g[member_key]["id"]
        if 0 <= idx < len(team) and team[idx]["id"] == mid:
            team.pop(idx)
        else:
            team = [m for m in team if m["id"] != mid]
            g["team_members"] = team
        if not team:
            return False
        g["team_index"] = min(idx, len(team) - 1)
        g["player1"] = team[g["team_index"]]
        g["currentTurn"] = 1
        g["player1"]["drawCount"] = 0
        return True

    # ------------- 通用辅助 -------------
    def _new_player(self, event: AstrMessageEvent) -> dict:
        """创建一名新玩家的初始状态。"""
        return {
            "name": event.get_sender_name(),
            "id": event.get_sender_id(),
            "hp": 6,
            "items": [],
            "shield": False,
            "handcuff": False,
            "judgement": False,
            "timeZero": False,
            "weaken": False,
            "silenced": False,
            "nextLive": False,
            "hypnotized": False,
            "nextRevive": False,   # 蜕生：死亡时以2血复活（同局有效）
            "lifeSteal": False,    # 血鳞：免疫下次伤害并恢复等量生命
            "goldenEye": False,    # 黄金瞳：免疫下次伤害并反弹给攻击者
            "noDraw": False,       # 血脉诅咒：本回合禁抽
            "powerUp": 0,          # 怒焰：本回合伤害+1
            "drawn": False,        # 兼容旧存档字段，当前抽卡规则已不使用
            "drawCount": 0,
            "usedItems": 0,        # 本回合已使用言灵次数（PvP 每轮上限 3 次）
            "pity": 0,
            "legendPity": 0
        }

    def _touch(self, cid: str):
        """标记该对局有活动，用于无操作超时判定。"""
        if cid in self.games:
            self.games[cid]["last_activity"] = time.time()

    async def _private_send(self, event, text: str) -> bool:
        """
        尝试将消息私发给消息发送者（如 QQ 直聊）。
        目标会话 = {平台}:FriendMessage:{用户ID}；失败（平台不支持/异常）返回 False。
        """
        try:
            platform = event.get_platform_id()
            uid = event.get_sender_id()
            target = f"{platform}:FriendMessage:{uid}"
            await self.context.send_message(target, MessageChain().message(text))
            return True
        except Exception as e:
            logger.warning(f"[龙族轮盘] 私发消息失败: {e}")
            return False

    # ------------- 屠龙模式：Boss AI -------------
    async def _boss_turn(self, cid: str):
        """
        屠龙局：Boss 自动行动。
        决策：血量低先防御 → 有攻击言灵则咏唱 → 实弹多打人/空包多吞枪。
        若 Boss 保留行动权（吞空包/时间零等），自动递归继续行动。
        """
        try:
            await asyncio.sleep(1.2)
        except (asyncio.CancelledError, Exception):
            return
        if not await self._boss_act(cid):
            return
        # Boss 保留行动权时继续行动
        g = self.games.get(cid)
        if g and g.get("boss") and g["status"] == STATUS_STARTED and g["currentTurn"] == 2:
            await self._boss_turn(cid)

    async def _boss_act(self, cid: str) -> bool:
        """执行一次 Boss 行动（防御/攻击/开枪）。返回是否成功执行。"""
        g = self.games.get(cid)
        if not g or not g.get("boss") or g["status"] != STATUS_STARTED or g["currentTurn"] != 2:
            return False
        boss_p, human_p = g["player2"], g["player1"]
        if human_p["hp"] <= 0 or boss_p["hp"] <= 0:
            return False
        origin = g.get("origin")
        max_hp = g.get("bossMaxHp", 6)

        # 1) 防御：血量低且有防御言灵
        if boss_p["hp"] < max_hp * 0.4:
            for skill in ("言灵·青铜御座", "言灵·无尘之地", "言灵·冬", "言灵·归墟"):
                if skill in boss_p["items"]:
                    await self._boss_use_skill(cid, skill)
                    return self._boss_alive(cid)

        # 2) 攻击言灵
        for skill in ("言灵·君焰", "言灵·烛龙", "言灵·审判", "言灵·皇帝", "言灵·湿婆业舞"):
            if skill in boss_p["items"]:
                await self._boss_use_skill(cid, skill)
                if not self._boss_alive(cid):
                    return False
                break

        g = self.games.get(cid)
        if not g or g["status"] != STATUS_STARTED or g["currentTurn"] != 2:
            return False
        boss_p, human_p = g["player2"], g["player1"]
        if human_p["hp"] <= 0 or boss_p["hp"] <= 0:
            return False

        # 3) 开枪决策：实弹多→打人；空包多→吞枪（保留行动权）
        bullets = g.get("bullet", [])
        if not bullets:
            return False
        live = self.count_bullet(bullets, BULLET_LIVE)
        blank = len(bullets) - live
        target = "对方" if live >= blank else "自己"

        class _BossEvent:
            def get_sender_id(self): return boss_p["id"]
            def get_sender_name(self): return boss_p["name"]
            def get_platform_id(self): return "boss"
            def plain_result(self, text): return SimpleNamespace(kind="plain", text=text)
            def image_result(self, p): return SimpleNamespace(kind="image", path=p)

        results = []
        async for r in self.fire(cid, target, _BossEvent()):
            results.append(r)
        for r in results:
            text = getattr(r, "text", None)
            if text and origin:
                try:
                    await self.context.send_message(origin, MessageChain().message(text))
                except Exception:
                    pass
        return True

    def _boss_alive(self, cid: str) -> bool:
        """Boss 行动后是否仍可继续（对局存在且轮到 Boss）。"""
        g = self.games.get(cid)
        if not g or g["status"] != STATUS_STARTED or g["currentTurn"] != 2:
            return False
        return g["player1"]["hp"] > 0 and g["player2"]["hp"] > 0

    async def _boss_use_skill(self, cid: str, skill: str):
        """Boss 施展专属言灵并在群内播报。"""
        g = self.games.get(cid)
        if not g or skill not in g["player2"]["items"]:
            return
        origin = g.get("origin")
        g["player2"]["items"].remove(skill)
        info = self.item_list.get(skill, {})
        if info.get("chant"):
            msgs = [f"🗣️ 龙王低吟：{info['chant']}"]
        else:
            msgs = [f"🗣️ 龙王低吟：【{skill}】！"]
        fn = info.get("use")
        try:
            if fn:
                ev = SimpleNamespace(
                    get_sender_id=lambda: g["player2"]["id"],
                    get_sender_name=lambda: g["player2"]["name"],
                    get_platform_id=lambda: "boss",
                )
                res = await fn(self, cid, "player2", None, ev)
                if isinstance(res, (list, tuple)):
                    msgs.extend(res)
                elif res:
                    msgs.append(str(res))
        except Exception as e:
            logger.warning(f"[龙族轮盘] Boss 施展 {skill} 失败: {e}")
            msgs.append("……言灵的领域剧烈震荡，未能完全展开。")
        if cid in self.games:
            self._touch(cid)
        # 即使技能导致对局结束（self.games[cid] 已被删除），也要把结算播报发出去
        if origin:
            try:
                await self.context.send_message(origin, MessageChain().message("\n".join(msgs)))
            except Exception:
                pass

    def resolve_damage(self, cid: str, g: dict, target_key: str, amount: int, msgs: list):
        """
        统一伤害结算：护盾抵消 → 扣血 → 死亡结算胜负。
        返回 (msgs, finished, shielded)：
          - finished=True 表示对局已结束，调用方应直接 return；
          - shielded=True 表示伤害被护盾完全抵消（本次未造成实际扣血）。
        """
        target = g[target_key]
        oth_key = other_player(target_key)
        if target.get("shield", False):
            target["shield"] = False
            msgs.append("但对方的青铜御座闪耀，将伤害全部吸收！")
            return msgs, False, True
        target["hp"] -= amount
        msgs.append(f"对方损失 {amount} 点生命！")
        if target["hp"] <= 0:
            if target.get("nextRevive", False):
                # 蜕生：死亡边缘复活
                target["nextRevive"] = False
                target["hp"] = 2
                msgs.append(f"🐣 蜕生发动！{self.at_id(target['name'])} 于死亡边缘重燃龙血，以 2 点生命复活！")
                return msgs, False, False
            if g.get("team_hunt") and target_key == "player1":
                if self._remove_team_member(g):
                    msgs.append(f"{self.at_id(target['name'])} 倒下了！")
                    msgs.append(f"⛑ 讨伐队仍有成员存活，{g['player1']['name']} 接替行动！")
                    return msgs, False, False
                # 全灭则继续走失败结算（由下方统一追加死亡/胜负消息）
            msgs.append(f"{self.at_id(target['name'])} 倒下了！")
            msgs.append(f"{self.at_id(g[oth_key]['name'])} 获得了最终胜利！")
            msgs.extend(self.game_over(cid, winner=oth_key, loser=target_key))
            return msgs, True, False
        return msgs, False, False

    # ------------- 持久化 & 守护任务 -------------
    def save_games(self):
        """将进行中的对局保存到插件数据目录（升级插件不会被覆盖）。"""
        if not self.games:
            return
        try:
            os.makedirs(PLUGIN_DATA_DIR, exist_ok=True)
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(self.games, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[龙族轮盘] 保存对局失败: {e}")

    def load_games(self):
        """重启后恢复进行中的对局（等待加入的残局不恢复）。"""
        if not os.path.exists(STATE_FILE):
            return
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            restored = 0
            for cid, g in data.items():
                if not isinstance(g, dict) or g.get("status") != STATUS_STARTED:
                    continue
                valid = True
                for key in ("player1", "player2"):
                    if key not in g or not isinstance(g[key], dict):
                        valid = False
                        break
                if not valid:
                    continue
                # 组队局恢复时把 player1 重新指向当前队员，避免 JSON 反序列化导致引用断裂
                if g.get("team_hunt") and isinstance(g.get("team_members"), list) and g["team_members"]:
                    idx = min(g.get("team_index", 0), len(g["team_members"]) - 1)
                    g["player1"] = g["team_members"][idx]
                g["last_activity"] = time.time()
                self.games[cid] = g
                restored += 1
            if restored:
                logger.info(f"[龙族轮盘] 已恢复 {restored} 局进行中的对局")
        except Exception as e:
            logger.warning(f"[龙族轮盘] 恢复对局失败: {e}")

    async def _watchdog_loop(self):
        """守护任务：定期持久化，并自动结束长时间无操作的对局。"""
        while True:
            await asyncio.sleep(WATCHDOG_INTERVAL)
            try:
                if self.config.get("persistGames"):
                    self.save_games()
                timeout = self.config.get("gameTimeout") or 0
                if timeout > 0:
                    now = time.time()
                    for cid in list(self.games):
                        g = self.games[cid]
                        if g.get("status") != STATUS_STARTED:
                            continue
                        last = g.get("last_activity", now)
                        if now - last > timeout * 60:
                            origin = g.get("origin")
                            lines = self.void_game(cid, f"对局因长时间无操作（>{timeout} 分钟）已自动结束，本局作废。")
                            if origin:
                                await self.context.send_message(
                                    origin,
                                    MessageChain().message("\n".join(lines))
                                )
                            logger.info(f"[龙族轮盘] 对局 {cid} 超时自动结束")
            except Exception as e:
                logger.warning(f"[龙族轮盘] 守护任务出错: {e}")

    # ------------- 龙币积分 & 押注 -------------
    def _load_economy(self):
        """加载龙币/战绩档案（始终持久化，与 persistGames 无关）。"""
        if not os.path.exists(ECO_FILE):
            return
        try:
            with open(ECO_FILE, "r", encoding="utf-8") as f:
                self.economy = json.load(f)
        except Exception as e:
            logger.warning(f"[龙族轮盘] 加载龙币档案失败: {e}")
            self.economy = {}

    def _save_economy(self):
        try:
            os.makedirs(PLUGIN_DATA_DIR, exist_ok=True)
            with open(ECO_FILE, "w", encoding="utf-8") as f:
                json.dump(self.economy, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[龙族轮盘] 保存龙币档案失败: {e}")

    def _get_user(self, uid: str, name: str = "") -> dict:
        """获取（或创建）一名玩家的龙币档案。"""
        if uid not in self.economy:
            self.economy[uid] = {
                "name": name,
                "coins": self.config.get("startCoins", 100),
                "wins": 0,
                "losses": 0,
                "streak": 0,
                "max_streak": 0,
                "bets_won": 0,
                "bets_lost": 0,
                "bosses": {},   # 屠龙击杀记录：{Boss名: 次数}
            }
        elif name and self.economy[uid].get("name") != name:
            self.economy[uid]["name"] = name
        return self.economy[uid]

    def _refund_bets(self, cid: str) -> int:
        """把该对局的全部押注退还给下注者，返回退款总额。"""
        g = self.games.get(cid)
        if not g:
            return 0
        total = 0
        for b in g.get("bets", []):
            u = self._get_user(b["uid"], b.get("name", ""))
            u["coins"] += b["amount"]
            total += b["amount"]
        if total:
            self._save_economy()
        return total

    def _settle(self, cid: str, winner_key: str, loser_key: str) -> list:
        """
        对局结算：胜负龙币 + 连胜加成 + 押注派彩（1:1 赔率）。
        返回播报行列表；下注者在押注时已扣除本金，押中者此处返还本金+赢额。
        """
        g = self.games[cid]
        lines = []
        w = self._get_user(g[winner_key]["id"], g[winner_key]["name"])
        l = self._get_user(g[loser_key]["id"], g[loser_key]["name"])
        win_reward = self.config.get("winReward", 30)
        lose_reward = self.config.get("loseReward", 10)
        streak = w.get("streak", 0) + 1
        bonus = min(streak, 5) * self.config.get("streakBonus", 5)
        w["wins"] = w.get("wins", 0) + 1
        w["streak"] = streak
        w["max_streak"] = max(w.get("max_streak", 0), streak)
        w["coins"] = w.get("coins", 0) + win_reward + bonus
        l["losses"] = l.get("losses", 0) + 1
        l["streak"] = 0
        l["coins"] = l.get("coins", 0) + lose_reward
        lines.append(f"💰 {g[winner_key]['name']} +{win_reward + bonus} 龙币（胜场 {win_reward} + 连胜加成 {bonus}）")
        lines.append(f"💰 {g[loser_key]['name']} +{lose_reward} 龙币（参与安慰）")
        # 押注派彩
        bets = g.get("bets", [])
        if bets:
            won_total = 0
            lost_total = 0
            detail = []
            for b in bets:
                u = self._get_user(b["uid"], b.get("name", ""))
                if b["side"] == winner_key:
                    u["coins"] = u.get("coins", 0) + b["amount"] * 2  # 本金返还 + 赢额
                    u["bets_won"] = u.get("bets_won", 0) + 1
                    won_total += b["amount"]
                    detail.append(f"  🎯 {b.get('name', '匿名')} 押中，赢 {b['amount']} 龙币")
                else:
                    u["bets_lost"] = u.get("bets_lost", 0) + 1
                    lost_total += b["amount"]
                    detail.append(f"  💨 {b.get('name', '匿名')} 押失，输 {b['amount']} 龙币")
            lines.append(f"💰 押注结算：押中者共赢 {won_total}，押失者共输 {lost_total}")
            lines.extend(detail[:8])
            if len(detail) > 8:
                lines.append(f"  ……等共 {len(detail)} 笔")
        self._save_economy()
        return lines

    def _settle_boss(self, cid: str, human_win: bool) -> list:
        """
        屠龙结算：胜 → 发放 Boss 奖励并记录击杀；负 → 入场费已消耗。
        注意：必须在删除 games[cid] 前调用。
        """
        g = self.games[cid]
        boss_key = g.get("boss", "诺顿")
        lines = []
        if human_win:
            rewards = self.config.get("dragonRewards", [50, 80, 100, 150])
            base_reward = rewards[BOSS_ORDER.index(boss_key)] if boss_key in BOSS_ORDER else 50
            if g.get("team_hunt"):
                recipients = list(g.get("team_members", [])) or [g["player1"]]
                reward = max(1, base_reward // len(recipients))
                for m in recipients:
                    u = self._get_user(m["id"], m["name"])
                    u["coins"] = u.get("coins", 0) + reward
                    bosses = u.setdefault("bosses", {})
                    bosses[boss_key] = bosses.get(boss_key, 0) + 1
                names = "、".join(m["name"] for m in recipients)
                lines.append(f"💰 屠龙成功！讨伐队每人获得 {reward} 龙币（总奖励 {base_reward} 分给 {len(recipients)} 人）。")
                lines.append(f"📜 讨伐记录：{names}")
            else:
                human = self._get_user(g["player1"]["id"], g["player1"]["name"])
                reward = base_reward
                human["coins"] = human.get("coins", 0) + reward
                bosses = human.setdefault("bosses", {})
                bosses[boss_key] = bosses.get(boss_key, 0) + 1
                lines.append(f"💰 屠龙成功！获得 {reward} 龙币（累计讨伐 {bosses[boss_key]} 次）。")
        else:
            fee = self.config.get("dragonFee", 20)
            lines.append(f"💰 挑战失败，入场费 {fee} 龙币已消耗，Boss 依旧盘踞深渊。")
        self._save_economy()
        return lines

    def void_game(self, cid: str, reason: str) -> list:
        """
        作废对局（强制结束/超时）：退还全部押注，不计胜负，不发放奖励。
        返回播报行列表。
        """
        g = self.games.get(cid)
        if not g:
            return []
        lines = [f"══ 🐉 龙族轮盘 ══\n{reason}"]
        bets_refund = self._refund_bets(cid)
        fee_refund = 0
        if g.get("boss") and g.get("status") == STATUS_STARTED:
            fee = self.config.get("dragonFee", 20)
            if g.get("team_hunt"):
                for m in g.get("team_members", []):
                    u = self._get_user(m["id"], m["name"])
                    u["coins"] = u.get("coins", 0) + fee
                fee_refund = fee * len(g.get("team_members", []))
            else:
                u = self._get_user(g["player1"]["id"], g["player1"]["name"])
                u["coins"] = u.get("coins", 0) + fee
                fee_refund = fee
        if fee_refund:
            lines.append(f"💰 屠龙入场费 {fee_refund} 龙币已退还。")
        if bets_refund:
            lines.append(f"💰 押注已全部退还（共 {bets_refund} 龙币）。")
        if fee_refund or bets_refund:
            self._save_economy()
        del self.games[cid]
        return lines

    def status_text(self, player: dict) -> str:
        """返回玩家身上的言灵状态文本"""
        statuses = []
        if player.get("shield"):
            statuses.append("🛡青铜御座")
        if player.get("handcuff"):
            statuses.append("⛓王权束缚")
        if player.get("judgement"):
            statuses.append("⚖审判压制")
        if player.get("timeZero"):
            statuses.append("⏳时间零")
        if player.get("weaken"):
            statuses.append("🌞炽日压制")
        if player.get("silenced"):
            statuses.append("🔇戒律封印")
        if player.get("nextLive"):
            statuses.append("🔥烛龙预热")
        if player.get("hypnotized"):
            statuses.append("😴催眠")
        if player.get("nextRevive"):
            statuses.append("🐣蜕生")
        if player.get("lifeSteal"):
            statuses.append("🩸血鳞")
        if player.get("noDraw"):
            statuses.append("🚫禁抽")
        if player.get("powerUp"):
            statuses.append("⚡怒焰")
        if player.get("goldenEye"):
            statuses.append("👁️黄金瞳")
        return "、".join(statuses) if statuses else ""

    # ------------- 对战面板图片化（Pillow 渲染） -------------
    _FONT_CANDIDATES = (
        "C:/Windows/Fonts/msyhbd.ttc",
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    )
    _STATUS_LABELS = (
        ("shield", "护盾"), ("handcuff", "王权"), ("judgement", "审判"),
        ("timeZero", "时间零"), ("weaken", "炽日压制"), ("silenced", "戒律"),
        ("nextLive", "烛龙预热"), ("hypnotized", "催眠"), ("nextRevive", "蜕生"),
        ("lifeSteal", "血鳞"), ("noDraw", "禁抽"), ("powerUp", "怒焰"),
        ("goldenEye", "黄金瞳"),
    )
    _RARITY_COLORS = {"普通": (170, 175, 190), "稀有": (96, 158, 255), "传说": (240, 182, 64)}

    def _panel_font(self, size: int):
        from PIL import ImageFont

        for path in self._FONT_CANDIDATES:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except Exception:
                    continue
        return ImageFont.load_default()

    def _render_battle_panel(self, g: dict):
        """
        将对战信息渲染为 PNG（返回保存路径）。
        依赖 Pillow 与系统中文字体；任何环节失败均返回 None，由调用方回退文本面板。
        """
        try:
            from PIL import Image, ImageDraw
        except Exception:
            return None
        try:
            mode = g.get("mode", "标准")
            cfg = self.get_mode_config(mode)
            p1, p2 = g["player1"], g["player2"]
            cur_p = f"player{g['currentTurn']}"
            bullets = g.get("bullet", [])
            live = self.count_bullet(bullets, BULLET_LIVE)
            blank = len(bullets) - live
            bets = g.get("bets", [])

            W = 940
            PAD = 40
            f_title = self._panel_font(46)
            f_name = self._panel_font(34)
            f_body = self._panel_font(27)
            f_small = self._panel_font(23)
            f_chip = self._panel_font(21)

            def hp_color(pct: float):
                # 低血红 -> 高血绿
                r = int(225 - 155 * pct)
                gg = int(60 + 130 * pct)
                b = int(60 + 50 * pct)
                return (r, gg, b)

            def item_rows(player):
                return [(it, self.item_list.get(it, {}).get("description", "")) for it in player["items"]]

            rows1, rows2 = item_rows(p1), item_rows(p2)

            def card_h(rows):
                # 名字行 + 血条 + 状态行 + 言灵列表 + 底部留白
                return 46 + 52 + 44 + max(1, len(rows)) * 36 + 24

            h1, h2 = card_h(rows1), card_h(rows2)
            bet_h = 58 if bets else 0
            footer_h = 84
            H = PAD + 120 + h1 + 22 + h2 + bet_h + footer_h + PAD

            img = Image.new("RGB", (W, H), (15, 17, 30))
            d = ImageDraw.Draw(img)
            d.rectangle([0, 0, W, 8], fill=(200, 150, 50))
            d.rectangle([0, H - 8, W, H], fill=(200, 150, 50))

            y = PAD
            d.text((PAD, y), "龙族轮盘 · 对战面板", font=f_title, fill=(236, 236, 246))
            y += 58
            d.text(
                (PAD, y),
                f"模式：{mode} ｜ 第 {g.get('round', 1)} 轮 ｜ 弹夹剩余 {len(bullets)} 发（龙炎 {live} ｜ 空包 {blank}）",
                font=f_small, fill=(158, 164, 186),
            )
            y += 46
            d.line([(PAD, y), (W - PAD, y)], fill=(200, 150, 50), width=2)
            y += 20

            for player, rows, is_cur, max_hp in (
                (p1, rows1, cur_p == "player1", cfg["hp"]),
                (p2, rows2, cur_p == "player2", g.get("bossMaxHp", cfg["hp"])),
            ):
                ch = card_h(rows)
                d.rounded_rectangle([PAD, y, W - PAD, y + ch], radius=18, fill=(26, 30, 50), outline=(52, 60, 92))
                name_color = (240, 196, 84) if is_cur else (226, 228, 238)
                name_text = ("◆ " if is_cur else "· ") + player["name"] + ("  当前行动" if is_cur else "")
                d.text((PAD + 22, y + 16), name_text, font=f_name, fill=name_color)
                # 血条
                pct = max(0.0, min(1.0, player["hp"] / max_hp)) if max_hp else 0.0
                bar_x, bar_y, bar_w, bar_h = PAD + 22, y + 72, 380, 22
                d.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=11, fill=(18, 20, 36), outline=(70, 78, 110))
                if pct > 0:
                    d.rounded_rectangle(
                        [bar_x + 2, bar_y + 2, bar_x + 2 + int((bar_w - 4) * pct), bar_y + bar_h - 2],
                        radius=9, fill=hp_color(pct),
                    )
                d.text((bar_x + bar_w + 18, bar_y - 6), f"{player['hp']}/{max_hp}", font=f_body, fill=(240, 240, 248))
                # 状态标签
                sx, sy = PAD + 22, y + 112
                for key, label in self._STATUS_LABELS:
                    if player.get(key):
                        tw = d.textlength(label, font=f_chip)
                        d.rounded_rectangle([sx, sy, sx + tw + 20, sy + 30], radius=15, fill=(48, 56, 88))
                        d.text((sx + 10, sy + 2), label, font=f_chip, fill=(176, 190, 226))
                        sx += tw + 32
                # 言灵列表
                iy = y + 158
                if not rows:
                    d.text((PAD + 22, iy), "· （暂无言灵，发送“抽”消耗生命抽取）", font=f_small, fill=(120, 126, 148))
                else:
                    for it, desc in rows:
                        rc = self._RARITY_COLORS.get(self.item_list.get(it, {}).get("rarity", "普通"))
                        d.text((PAD + 22, iy), "· " + it, font=f_body, fill=rc)
                        if desc:
                            d.text(
                                (PAD + 22 + d.textlength("· " + it, font=f_body) + 12, iy + 2),
                                "—— " + desc, font=f_small, fill=(150, 156, 178),
                            )
                        iy += 36
                y += ch + 22

            if bets:
                p1_total = sum(b["amount"] for b in bets if b["side"] == "player1")
                p2_total = sum(b["amount"] for b in bets if b["side"] == "player2")
                state = "已封盘" if g["status"] == STATUS_STARTED else "可下注"
                d.rounded_rectangle([PAD, y, W - PAD, y + bet_h], radius=14, fill=(40, 34, 46), outline=(140, 110, 60))
                d.text(
                    (PAD + 22, y + 13),
                    f"押注：玩家1 {p1_total} ｜ 玩家2 {p2_total} 龙币（{state}）",
                    font=f_body, fill=(238, 200, 110),
                )
                y += bet_h + 22

            d.text((PAD, y), "发送“开枪/对方”攻击 ｜ “吞枪/自己”开枪 ｜ “抽”抽卡 ｜ 言灵名咏唱", font=f_small, fill=(120, 126, 148))
            y += 34
            d.text((PAD, y), "“认输”投降 ｜ “丢弃 言灵名”清理背包 ｜ “信息”刷新本面板", font=f_small, fill=(120, 126, 148))

            os.makedirs(PLUGIN_DATA_DIR, exist_ok=True)
            out_path = os.path.join(PLUGIN_DATA_DIR, "battle_panel.png")
            img.save(out_path, "PNG")
            return out_path
        except Exception as e:
            logger.warning(f"[龙族轮盘] 渲染对战面板失败: {e}")
            return None

    def at_id(self, nickname: str) -> str:
        """
        以纯文本形式提及玩家，跨平台通用（不依赖 CQ 码/富文本 @）。
        如需真正的平台 @，可在消息链中使用 MessageSegment.at(用户ID)。
        """
        return f"@{nickname}"
