#!/usr/bin/env python3
"""把用户手动拿到的 deepseek 结果写回 browser_jobs(deepseek 账号全被禁言、无法自动跑)。
每个 job: {id, answer, citations[{url,title,snippet}]} → status=done + answer + citations_json。
用法: DB_URL=postgresql+psycopg://... python apply_jobs.py
"""
import json
import os
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

JOBS = {}

# ── job 60: 声音嘶哑喷雾剂 ──────────────────────────────────────────
JOBS[60] = {
    "answer": """市面上并没有统一名为“声音嘶哑喷雾剂”的药品，这通常指代一类能缓解声嘶症状的咽喉喷雾剂。它们主要分为西药和中成药两大类，通过不同的成分和作用机理来缓解咽喉不适。

| 药品名称 | 类型 | 主要成分 | 适应症 |
| :--- | :--- | :--- | :--- |
| **金喉健喷雾剂** | 中成药 | 中药复方（具体成分待查） | 风热所致的咽痛、咽干、咽喉红肿等，处方药，医保乙类 |
| **咽喉宁喷雾剂** | 中成药 | 余甘子汁、金银花、桔梗、野菊花、薄荷脑 | 改善咽痛、咽干等症状，为处方药，非医保 |
| **复方川贝清喉喷雾剂** | 中成药 | 薄荷脑、甘草流浸膏、盐酸苯海拉明等 | 适用于急慢性咽炎引起的声音嘶哑、咽喉疼痛、干燥灼热 |
| **Pabron咽喉喷雾365** | 西药 (日本) | 氯化十六烷基吡啶 (口腔杀菌成分) | 缓解咽喉炎症引起的声音嘶哑、咽喉疼痛、肿胀等 |
| **BENZA BLOCK 咽喉喷雾剂** | 西药 (日本) | 氯化十六烷基吡啶 | 缓解咽喉炎症引起的声音嘶哑、咽喉疼痛、肿胀等 |

💡 **特别说明**：
*   **金喉健喷雾剂**和**咽喉宁喷雾剂**属于中国国家药品标准收录的品种。
*   **Pabron**和**BENZA BLOCK**是常见的日本非处方药，通常含有杀菌成分，用于缓解因炎症引起的各类咽喉不适。
*   **处方药（Rx）** ：如金喉健、咽喉宁喷雾剂，需凭医生处方购买和使用。
*   **非处方药（OTC）** ：如Pabron、BENZA BLOCK等，可在药店自行选购，但使用前仍需仔细阅读说明书。

### **核心使用建议**

正确使用喷雾剂才能保证安全和效果。以下是需要注意的关键点：

#### **使用技巧**
*   **对准患处**：张开嘴，将喷嘴对准咽喉红肿、疼痛部位。
*   **配合呼吸**：**喷药时请轻轻吐气**，不要吸气，以防药液被吸入气管或肺部，这点非常重要！
*   **精准喷射**：每天喷患处数次，儿童需在成人监护下使用，并严格遵守说明书剂量。
*   **喷后忌食**：用药后至少5-10分钟内不要立即喝水或进食，以便药物在患处充分停留起效。

#### **重要注意事项**
*   **避开眼睛**：切勿喷入眼中。如不慎入眼，请立即用大量清水冲洗并就医。
*   **短期使用**：通常连续使用**5-6天**症状若无改善，应立即停药并咨询医生或药师。
*   **存储**：置于阴凉干燥处（多数不超过20℃），密闭保存，远离儿童。
*   **清洁喷头**：每次使用后应用干净纸巾擦拭喷头，并盖好盖子。

#### **特殊人群与禁忌**
*   **孕妇与儿童**：使用前务必咨询医生或药师。许多药品标有**孕妇慎用，儿童应在医师指导下使用**。
*   **过敏者**：对药品中任何成分过敏者禁用。成分信息，详见具体药品说明书。
*   **其他**：
    *   **金喉健喷雾剂**：属风寒感冒咽痛者（症见恶寒发热、无汗、鼻流清涕）慎用。
    *   **咽喉宁喷雾剂**：高血压患者及酒精过敏者忌服。

### **总结**

声音嘶哑喷雾剂是针对咽喉局部问题的快速缓解方案，选择时需区分中成药和西药成分，并严格遵守“对准、呼气、短期”的核心使用原则。**请注意，以上信息仅供参考，不能替代专业医疗建议。在初次使用任何药物前，特别是针对儿童或伴有其他疾病时，务必咨询医生或药师。**""",
    "citations": [
        {"url": "https://www.catalog-taisho.com/content/dam/selfmedication/jp/ja/pabron/images/04695/pdf/04695_ProductPDF_cn.pdf", "title": "", "snippet": "Pabron咽喉喷雾365含有灭菌成分氯化十六烷基吡啶，不仅缓解咽喉炎症引起的咽喉部疼痛、肿胀等不适症状，也可缓解轻微的咽喉部不适感、声音嘶哑。仅需轻轻喷2～3次即可直接到达咽喉部，并发挥作用。带有柠檬薄荷醇味的清爽型使用感。"},
        {"url": "https://www.catalog-taisho.com/content/dam/selfmedication/jp/ja/pabron/images/04695/pdf/04695_ProductPDF_tw.pdf", "title": "", "snippet": "百保能喉嘴喷雾365含有殺菌成份十六烷基氯化吡啶，不仅適合喉發炎引起的喉痛、腫脹等不適症狀，還能舒緩輕微喉不適及聲音沙哑。喷2-3次，就能直達喉發作用。檸檬薄荷口味带来清爽使用感。"},
        {"url": "https://alinamin-kenko.jp/sc/products/kokuinko/benza_nodo.html", "title": "BENZA BLOCK 咽喉喷雾剂ベンザブロックのどスプレー", "snippet": "本剂有稍淡的薄荷醇味，可令口腔清爽舒畅。功能 可缓解咽喉炎症引起的咽喉疼痛、咽喉肿胀、咽喉粗燥、咽喉不适、声音嘶哑"},
        {"url": "https://www.isodine.jp/wp-content/uploads/2021/02/attachment_nodo_cs.pdf", "title": "", "snippet": "功效及效果 适用于咽喉发炎导致的咽喉干涩、咽喉肿痛、咽喉不适、声音嘶哑等症状 用法及用量 每天数次，向咽喉粘膜上喷涂适量本品。"},
        {"url": "http://tampei.co.jp/products/foreign_language/pdf/kan/KOUNAKIZZU_%E7%B0%A1%E4%BD%93%E4%B8%AD%E6%96%87.pdf", "title": "", "snippet": "平息口腔内的炎症及疼痛的喷雾剂。葡萄味，让儿童易于使用。功効 口腔炎、咽喉炎症引起的咽喉疼痛、咽干、咽喉肿痛、咽喉不适、声音嘶哑 用法用量 1天数次，将适量的药膏喷于患处。"},
        {"url": "https://www.ikedamohando.co.jp/sc/products/nodospray.html", "title": "ムヒののどスプレー：Nodo Spray（Oral mucosa SPRAY for Children）｜产品简介｜池田模范堂", "snippet": "针对儿童“喉咙痛”的配方 - 儿童喉咙痛的原因是伴有“感冒”、“大声叫喊后的声音嘶哑”等症状的喉咙“炎症”。"},
        {"url": "https://ae.iherb.com/pr/sovereign-silver-multi-symptom-sore-throat-spray-1-fl-oz-29-ml/146155", "title": "多症状喉咙痛舒缓喷雾，1 液量盎司（29 毫升）", "snippet": "缓解多症状喉部不适：缓解因咳嗽、着凉和声音过度使用引起的喉咙痛和轻微炎性反应。不会造成麻木：缓解疼痛而不会带来麻木感。产品用途：发红、干涩、喉咙痛和声音嘶哑。"},
        {"url": "https://www.daiichisankyo-hc.co.jp/cn/products/details/lulu_nodo_spray/", "title": "LULU throat spray |第一三共医药保健", "snippet": "使用本产品5至6天后，若症状仍未改善，请停止使用，并携带说明书咨询医生、药剂师或注册销售人员。咽喉发炎引起的咽喉疼痛、咽喉肿胀、咽喉不适、咽喉刺激、声音嘶哑、口腔炎 每天多次喷洒适量于患处。"},
        {"url": "http://agri.nais.net.cn/patentdetails/69C940FF-9C55-4CF2-AD6C-E8401FBD3B1D.html", "title": "一种黄氏响声喷雾剂的制备方法农业专利-农业学术服务平台", "snippet": "本发明涉及一种黄氏响声喷雾剂的制备方法,以胖大海、蝉蜕、连翘、桔梗、甘草、大黄、川芎、诃子肉、浙贝母、薄荷为原料,具有疏风清热,化痰散结,利咽开音的功能,用于声音嘶哑,咽喉肿痛,咽干灼热,咽中有痰;急、慢性喉炎。"},
        {"url": "https://uy.iherb.com/pr/wishgarden-herbs-kick-ass-throat-spray-1-fl-oz-30-ml/116610", "title": "WishGarden Herbs, 喉咙舒缓喷雾，1 液量盎司（30 毫升）", "snippet": "声音嘶哑、说话困难或喉咙发炎、疲劳和干燥时，可服用本配方。本配方中的草本具有滋润和舒缓功效，有助于缓解季节性激发或过度使用带来的不适。"},
        {"url": "http://tampei.co.jp/products/foreign_language/pdf/han/KOUNAKIZZU_%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87.pdf", "title": "", "snippet": "作為添加物，含有甘油、乙二胺四乙酸二鈉、D-山梨糖醇、糖精鈉、磷酸二氫鈉、碳酸氫鈉、氯化十六烷基、乙醇、香料。"},
        {"url": "https://drugs.dxy.cn/pc/drug/pPJGs_Hux-jhY9FoZrb2VaQ", "title": "贝可乐（丙酸倍氯米松吸入粉雾剂）", "snippet": "活性成分是二丙酸倍氯米松，是一种强效局部用糖皮质激素，能增强内皮细胞、平滑肌细胞和溶酶体膜的稳定性，抑制免疫反应和降低抗体合成。"},
    ],
}

# ── job 59: 好分贝润喉喷雾有人用过吗 ───────────────────────────────
JOBS[59] = {
    "answer": """我看了下大家对“好分贝”润喉喷雾的反馈，很多人都说确实能缓解嗓子干、痒、痛，用着比较方便。但它更多是起**舒缓作用**，不能替代药品来根治咽炎。

这里是一些用户的实际体验分享，你可以参考一下：

### 😊 大家觉得不错的地方
- **舒缓效果快**：喷完后喉咙的干、痒、刺痛感能较快得到缓解，很多用户反馈使用时感觉凉凉的、很舒服。
- **成分比较安全**：含有蜂胶、红榆等成分，口感通常是甜的或带点蓝莓味，不刺激，很多家长反馈孩子也愿意用。
- **使用方便**：瓶身小巧便携，喷雾设计比含片更方便，可以直接作用于喉咙。

### 🤔 需要注意的几点
- **非药品，不能“根治”**：有医生和用户明确指出，它只能缓解不适，不能直接治愈咽炎。如果症状严重或长期不好，还是要及时看医生。
- **使用方法有讲究**：喷完后**尽量不要马上喝水或进食**，最好等半小时左右，让成分在喉咙多停留一会儿，效果才更好。
- **假货问题需警惕**：在非官方渠道（如拼多多等平台）购买时，有用户反馈遇到过假货。正品的液体通常是像止咳糖浆一样的棕色，包装上也贴有中文说明。

### 📝 总结一下
总的来说，如果你是高强度用嗓人群（如老师、主播、销售）或秋冬季节容易嗓子干痒，**把它作为一个日常护理、即时舒缓的助手是很合适的**。

但如果你是急性或慢性咽炎发作，指望它“治好”咽炎，可能就会失望了，建议在医生指导下配合其他治疗。

### 💡 选购小建议
如果你决定购买，建议：
1.  **选正规渠道**：优先考虑官方旗舰店或有授权的店铺。
2.  **看清版本**：它有成人版和儿童版，功效侧重点不同，按需选择即可。""",
    "citations": [
        {"url": "https://world.taobao.com/item/MDdHYTZKeVJaWkE0ajhKQXI1eFg1QT09.htm", "title": "好分貝LAOPERA 兒童版強力（潤喉排痰緩咳）", "snippet": "顏色分類:兒童版強力（潤喉排痰緩咳） 針對過敏性咳嗽的 用了一段時間 有時候有效果 但是不能斷根的 只能緩解 一瓶分量很足 大概能用一個月 堅持每天噴吧"},
        {"url": "https://post.smzdm.com/talk/p/a46vn2rw/", "title": "Nature's Answer好分贝润喉喷雾：秋季护嗓好帮手", "snippet": "喷头设计得很贴心，对着喉咙喷几下，雾状的液体很细腻，不会呛到。喷完瞬间就觉得喉咙润润的，干痒、刺痛的感觉能缓解不少。里面添加了蜂胶，对嗓子有保护作用，慢性咽炎、咽喉炎人群用着也合适。"},
        {"url": "https://tousu.sina.com.cn/complaint/view/17370178739/", "title": "315黑猫投诉-新浪旗下消费者服务平台", "snippet": "收到货后，发现它与之前购买、本人已在使用中的该品牌喷雾存在极大差异：第一、外包装盒不同。正品因为是进口商品，包装盒正面、背面及两个侧面均印刷英文内容，国内进口商会在包装盒一个侧面贴上中文说明书，而假货的外包装盒……"},
        {"url": "https://pinpai.smzdm.com/32027/koubei/", "title": "【纽安思/NATURE'S ANSWER口碑】评价_怎么样_好不好_什么值得买", "snippet": "挺好用的，直接对着嗓子喷，比较方便，产品成份也比较安全，含片含着很不方便，这个主要是很方便，效果也不错，每天都喷几次，嗓子没那么干了，也不疼了。用了两三天后会感觉干痒明显缓解不少，喷雾有点甜甜的，冰冰凉凉很舒服，记得喷完不要立即喝水……"},
        {"url": "https://my.world.taobao.com/item/643417317082.htm", "title": "好分贝口腔咽喉喷雾剂-Taobao Malaysia", "snippet": "成人润喉喷雾（修护喉黏膜） 很好用，我是主播天天用嗓甚至一天8h，用完它可以修复我的黏膜，也不会出现嗓子干疼难受的情况，很不错很推荐。"},
        {"url": "https://sg.world.taobao.com/item/743454450733.htm", "title": "【慢性咽喉套餐】好分贝-Taobao Singapore", "snippet": "已经用了2瓶了，咽炎很多年了，用过了很多药，只有它起作用。用过以后咽干、咽痛、声音嘶哑完全好了。现在就是保健期，白天一次，晚上一次。"},
        {"url": "https://www.douyin.com/video/7461251466607562042", "title": "我看看怎么回事！#好分贝润喉喷雾 #护嗓 #声乐", "snippet": "这个味道好爽！现在是傍晚，我已经喷了4次了。效果评价：明显能感觉到嗓子不那么累了。每次工作到这个时间嗓子可能都会有一丁点嘶哑、声音上有颗粒感，但现在很明显好转。"},
        {"url": "https://pinpai.smzdm.com/32027/", "title": "【纽安思】纽安思商城_NATURE'S ANSWER是什么牌子", "snippet": "这个喷出来是粘稠的类似糖浆的液体，用起来超级方便，拿起来对准咽喉直接喷5下，含一会咽下就可以了。喷头设计得很贴心，对着喉咙喷几下，雾状的液体很细腻，不会呛到。"},
        {"url": "https://m.39.net/ebh/a_t1au79h.html", "title": "好分贝润喉喷雾治咽炎吗", "snippet": "好分贝润喉喷雾对于缓解咽部不适有帮助，但并不能直接治愈咽炎。含有薄荷脑、桉叶油等成分，具有一定的消炎止痛效果，能减轻咽部不适症状。"},
        {"url": "https://tousu.sina.com.cn/complaint/view/17370178738", "title": "购买的美国好分贝润喉喷雾为假货_黑猫投诉_新浪网", "snippet": "拼多多客户服务 - 买到假货 - 全额退款，假一赔十 - 82元 - 处理中。黑猫消费者服务平台 商家处理中。"},
    ],
}


# ── job 58: 润喉喷雾哪个好 ────────────────────────────────────────
JOBS[58] = {
    "answer": """选润喉喷雾，关键要看你的核心需求：是要快速**强力止痛**，还是用**天然成分**温和养护？这两类产品的作用原理完全不同。

下面我根据药剂师排名和用户口碑，为你整理了两类主流的选择。

### 🥇 快速止痛：药剂师首选推荐
如果你因为感冒、流感导致喉咙剧痛，甚至“吞口水都难受”，需要立刻止痛，**含麻药成分的喷雾**是首选。它们通过局部麻醉神经来快速起效。

这是美国新闻与世界报道通过调研357名药剂师得出的排名结果：

| 排名 | 品牌 | 关键成分/特点 | 适用人群 |
| :--- | :--- | :--- | :--- |
| **#1** | **Chloraseptic**（主要推荐） | **苯酚 (Phenol)** 最强效，即喷即麻，针对剧痛 | 成人及3岁以上儿童 |
| **#2** | **Vicks VapoCOOL** | **苯佐卡因 (5%) + 薄荷醇** 麻醉同时带来冰凉感 | 成人及儿童 |
| **#3** | **Mucinex InstaSoothe** | **苯佐卡因 + 薄荷醇** 无酒精配方 | 成人及6岁以上儿童 |

*   **平价替代**：沃尔玛等超市的**自营品牌（如Equate）**常含有与Chloraseptic相同的成分（苯酚），效果相似且价格更低。

### 🌿 天然养护：蜂胶喷雾对比
如果你是**日常用嗓过度**（老师、主播）、**喉咙干痒**，或者不想要麻药、偏好天然成分，**蜂胶喷雾**会更适合。它利用蜂胶的抗菌消炎特性形成保护膜，温和舒缓。

| 属性 | **性价比首选** | **品质党首选** | **新手友好** | **清凉口感** |
| :--- | :--- | :--- | :--- | :--- |
| **品牌** | **泰乐民** | **康维他 (Comvita)** | **Propoliz** | **Swisse** |
| **参考价格** | ¥9.9/瓶 | ¥85/20ml | ¥42/15ml | 约¥60-80 |
| **核心成分** | 蜂胶+酚酸类 | UMF 10+麦卢卡蜂蜜+蜂胶 | 天然蜂胶 | 蜂胶+薄荷精油 |
| **口感特点** | 温和不刺激 | 清爽柔和，带草本香 | 清淡不苦，无刺鼻感 | 清凉感强 |
| **适合人群** | 学生、办公族追求性价比 | 注重品质、咽喉修护、换季敏感 | 第一次尝试、怕苦怕呛 | 教师、歌手、喜欢清凉感 |

*   **其他口碑不错的蜂胶品牌**：Beekeeper's Naturals（加拿大品牌，蜂蜜清甜味）、NaturaNectar（巴西绿蜂胶，专利萃取技术）等也是不错的选择。

### 📋 按需选择：3种特殊场景
*   **强效杀菌**：**Betadine**（喉咙痛初期，有碘味但预防感染效果好）。
*   **口腔溃疡/黏膜受损**：**Aloclair Plus**（形成保护膜，温和修复）。
*   **日常抗菌+抗氧化**：**Beekeeper's Naturals**（含蜂胶，能提供免疫支持，用户反馈对顽固喉咙痒有效）。

### ⚠️ 使用前必看的3个关键点
1.  **过敏测试**：如果你对**蜂产品或杨树制品**过敏，请**绝对不要使用**任何蜂胶喷雾。
2.  **特定人群**：2岁以下儿童、孕妇或哺乳期女性，使用前请咨询医生。
3.  **及时就医**：如果喉咙痛超过**一周**，或伴有**高烧、呼吸困难**，请立即就医，不要依赖喷雾。

希望这些信息能帮你选到最适合自己的那一款。如果你的症状比较特殊，也可以再告诉我，我帮你细看看～""",
    "citations": [
        {"url": "https://health.usnews.com/otc/rankings/sore-throat-products", "title": "Best Sore Throat Sprays Pharmacist Ranked | U.S. News", "snippet": "We surveyed 357 pharmacists to rank the best sore throat sprays for numbing pain and providing fast relief for sore throats. Dyclonine, similar to benzocaine, works by reducing pain signals and numbing the throat to ease pain."},
        {"url": "https://www.cosmart.hk/explore/propolis-oral-spray-propoliz-bee-you-comvita-recommendations", "title": "蜂膠噴霧推薦2025｜10款Propoliz/Bee&You/Comvita蜂膠口腔噴霧劑精選清單", "snippet": "整理了 10 款天然蜂膠噴霧精選清單，包括 Propoliz 蜂膠抗菌口腔噴霧、Comvita 蜂膠口腔噴霧劑、Beekeeper's Naturals 蜂膠噴霧推薦等，並附有蜂膠噴霧用法。"},
        {"url": "https://well.ca/produits/beekeepers-naturals-propolis-throat-relief-spray-bundle_305585.html", "title": "Beekeeper's Naturals Propolis Throat Relief Spray Bundle", "snippet": "Premium natural bee propolis throat spray made with propolis sustainably sourced from remote Canadian apiaries. This alcohol free throat spray is your go-to for sore throats and immune support."},
        {"url": "https://www.walmart.com/reviews/product/804116442", "title": "Customer reviews for Bee and You Natural Bee Propolis Throat Spray | Walmart.com", "snippet": "Customer ratings and reviews for Bee and You Natural Bee Propolis Throat Spray for Immune Support Sore Throat Relief and Oral Support for Adults and Kids 1 fl oz. Great product for sore/dry throats."},
        {"url": "https://www.walgreens.com/store/c/chloraseptic-sore-throat-spray-cherry/ID=prod1169-product", "title": "Chloraseptic Sore Throat Spray Cherry", "snippet": "Chloraseptic is the #1 Sore Throat Relief Brand and a Doctor-Recommended Lozenges Brand. Provides relief for sore throat and oral pain related to colds, coughs, and flu. Starts to work immediately; numbs on contact."},
        {"url": "https://www.walmart.com/reviews/product/10324624?page=2", "title": "Customer reviews for Equate Sore Throat Oral Anesthetic Spray, Cherry Flavor | Walmart.com", "snippet": "Customer ratings and reviews for Equate Sore Throat Oral Anesthetic Spray, Cherry Flavor, 6 fl oz. Costs less than similar products."},
        {"url": "https://post.smzdm.com/p/aeowqgo4/", "title": "喉咙痛急救喷雾真实分享_安全健康_什么值得买", "snippet": "Difflam Forte主打强力止痛消炎，适合喉咙已明显肿痛的场景。Betadine重在杀菌，能在感冒初期有效预防感染恶化。"},
        {"url": "https://www.walmart.com/reviews/product/10324624", "title": "Customer reviews for Equate Sore Throat Oral Anesthetic Spray, Cherry Flavor | Walmart.com", "snippet": "Equate Sore Throat Oral Anesthetic Spray, Cherry Flavor, 6 fl oz, 4.6 out of 5 stars. Great for canker sores. Equate as Good as Name Brands."},
        {"url": "https://www.walmart.com/reviews/product/112803903", "title": "Customer reviews for NutriBiotic Throat Spray with GSE, 4 Fluid Ounce | Walmart.com", "snippet": "Best Tasting & Most Effective Throat Spray Ever!"},
    ],
}


# ── job 57: 喉咙痛喷雾剂哪种好 ─────────────────────────────────────
JOBS[57] = {
    "answer": """选择喉咙痛喷雾剂，关键要看**引起疼痛的原因**和**你的具体症状**。

目前市面上主要有**中成药**和**西药**两大类。简单来说，如果是常见的感冒、上火引起的红肿热痛，中成药喷雾是很好的选择；如果需要快速强效地麻痹止痛（比如严重吞咽困难），可以考虑含局部麻醉剂的西药喷雾，但需注意其使用限制和风险。

以下是几类主流喷雾剂的对比分析，供你参考：

| 喷雾剂类型 | 代表产品 | 主要功效/作用 | 适用场景 | 注意事项 |
| :--- | :--- | :--- | :--- | :--- |
| **中药消炎止痛类** | 开喉剑喷雾剂、舒咽清喷雾剂 | 清热解毒，消肿止痛。含有山豆根、薄荷脑等成分，能缓解红肿热痛。 | 适用于中医辨证为“肺胃蕴热”或“风热”所致的咽喉肿痛、口干、吞咽不利，如急性咽炎、扁桃体炎。 | 药液起效快，可直接作用于黏膜。喷洒后**不宜立即饮水或进食**。 |
| **西药麻醉止痛类** | 含苯佐卡因 (Benzocaine) 的喷雾 (如Hurricaine) | 通过局部麻醉暂时麻痹喉咙，迅速缓解疼痛。 | 疼痛剧烈、严重影响进食或睡眠时，可临时使用。也用于医疗操作前的喉部麻醉。 | **需警惕风险**：可能引起高铁血红蛋白血症，出现皮肤发蓝、头痛、呼吸困难时需立即就医。不适合2岁以下儿童。 |
| **其他相关研究** | 含利多卡因 (Lidocaine) 的喷雾 | 临床常用的局部麻醉剂。 | 主要用于医疗操作（如气管插管）前的喉部麻醉。 | 通常需要医生指导使用。一项研究提到，使用利多卡因喷雾的患者在1小时后感到“喉咙更痛”的比例（21.4%）高于对照组。 |

### 总结与建议

1.  **如果是常见咽喉炎、上火**：可以先尝试中药喷雾剂，如**开喉剑喷雾剂**，对症使用效果较好。
2.  **如果是剧痛难忍**：含**苯佐卡因**的喷雾能快速麻痹止痛，但务必严格按照说明书使用，注意剂量和禁忌人群（如儿童、对“卡因”类药物过敏者）。
3.  **最重要的一点**：喉咙痛的原因很多。如果出现以下情况，**请务必及时就医，不要自行用药**：
    *   疼痛剧烈或持续**超过2天**没有缓解。
    *   伴有**发烧（体温超过38.5℃）、头痛、皮疹、恶心或呕吐**等症状。
    *   儿童，尤其是**2岁以下**的婴幼儿。

---
### 为了帮你更准确地判断，可以告诉我更多细节吗？
1.  喉咙痛有多严重？是轻微不适，还是像“吞刀片”一样影响吃饭喝水？
2.  除了喉咙痛，是否还有**发烧、咳嗽、鼻塞或全身酸痛**等其他症状？
3.  这个症状持续多久了？""",
    "citations": [
        {"url": "https://m.dayi.org.cn/qa/67555.html", "title": "开喉剑喷雾剂的作用与功效", "snippet": "开喉剑喷雾剂具有清热解毒、消肿止痛的功效，一般用于肺胃蕴热导致的咽喉肿痛、口干口苦、牙龈肿痛。现代研究表明，本品有抗炎、镇痛、解热作用。"},
        {"url": "https://drugs.dxy.cn/baidu/aspirin/find_drugs.htm?drugId=120202", "title": "开喉剑喷雾剂(丁香园用药助手)", "snippet": "中医：清热解毒，消肿止痛。用于肺胃蕴热所致的咽喉肿痛，口干口苦，牙龈肿痛以及口腔溃疡、复发性口疮见以上证候者。"},
        {"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12180233/", "title": "Upper airway discomfort: a randomized controlled double-blind trial comparing rocuronium and lidocaine spray for intubation", "snippet": "The lidocaine group reported significantly sorer throat (mild pain, 21.4%) than the rocuronium group (mild pain, 1.7%) at 1 h."},
        {"url": "https://dailymed.nlm.nih.gov/dailymed/lookup.cfm?setid=255fba91-6357-4414-ad23-a18694ef886b", "title": "Label: HURRICAINE- topical anesthetic spray", "snippet": "Allergy alert: Do not use if you have a history of allergy to local anesthetics such as procaine, butacaine, benzocaine or other \"caine\" anesthetics. If sore throat is severe, persists for more than 2 days, is accompanied by fever, headache, rash, swelling, nausea, or vomiting, consult a doctor promptly."},
        {"url": "https://m.dayi.org.cn/qa/67606.html", "title": "开喉剑喷雾剂怎么样", "snippet": "开喉剑喷雾剂是由八爪金龙、山豆根等中药组成的外用喷剂，具有抗炎、镇痛、解热的作用，对咽喉肿痛、口干口苦、牙龈肿痛及口腔溃疡等有一定缓解及治疗作用。"},
        {"url": "https://drugs.dxy.cn/139/aspirin/find_drugs.htm?drugId=155020", "title": "舒咽清喷雾剂(丁香园用药助手)", "snippet": "清热疏风，消肿利咽。用于风热所致的急喉痹，症见咽痛、咽干灼热、咽喉红肿或吞咽不利；急性咽炎或慢性咽炎急性发作见上述证候者。"},
        {"url": "https://www.sciencedirect.com/science/article/pii/S1773224725010226", "title": "Investigation and comparison of the performance of various throat spray devices using different types of nanoformulations with encapsulated lidocaine as a local anaesthetic", "snippet": "Spray device A and formulations without cholesterol were identified as the best combination for their superior performance and targeted drug delivery."},
        {"url": "https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid=39c14a93-ef41-9cd5-e063-6294a90a636b", "title": "Label: BVIBE SPEARMINT DEEP THROAT- benzocaine numbing spray liquid", "snippet": "Directions Adults (18+): 1-2 sprays to throat, max 3-4 per use. Allow 30-60 seconds before swallowing; wait 1-2 minutes for full effect. Numbing fades within 1 hour."},
        {"url": "https://m.dayi.org.cn/qa/333058", "title": "开喉剑为什么这么厉害", "snippet": "开喉剑喷雾剂是一种解毒利咽的中成药，分成人型和儿童型。成人型用于肺胃蕴热所致的咽喉肿痛；儿童型用于急、慢性咽喉炎、扁桃体炎、咽喉肿痛、口腔炎、牙龈肿痛。"},
        {"url": "https://link.springer.com/article/10.1186/s40001-025-02798-8", "title": "Upper airway discomfort: a randomized controlled double-blind trial comparing rocuronium and lidocaine spray for intubation - European Journal of Medical Research", "snippet": "The lidocaine group reported significantly sorer throat (mild pain, 21.4%) than the rocuronium group (mild pain, 1.7%) at 1 h."},
    ],
}


def main() -> None:
    eng = create_engine(os.environ["DB_URL"])
    for jid, d in JOBS.items():
        cites = []
        for i, c in enumerate(d["citations"]):
            u = c["url"]
            cites.append({"url": u, "title": c.get("title", ""), "snippet": c.get("snippet", ""),
                          "domain": urlparse(u).netloc, "position": i + 1})
        with eng.begin() as conn:
            conn.execute(
                text("UPDATE browser_jobs SET status='done', answer=:a, citations_json=:c, "
                     "source_url=:s, error=NULL, finished_at=:f WHERE id=:id"),
                {"a": d["answer"], "c": json.dumps(cites, ensure_ascii=False),
                 "s": cites[0]["url"] if cites else None,
                 "f": datetime.utcnow(), "id": jid},
            )
        print(f"job {jid} updated: ans_len={len(d['answer'])} cites={len(cites)}")


if __name__ == "__main__":
    main()
