#!/usr/bin/env python3
"""把用户手动拿到的 deepseek 结果写回 browser_jobs id=60(声音嘶哑喷雾剂)。
deepseek 账号现在全被禁言,无法自动跑;用户从自己的会话拿到了答案+引用,直接落库。
用法: DB_URL=postgresql+psycopg://... python apply_job60.py
"""
import json
import os
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

JOB_ID = 60

ANSWER = """市面上并没有统一名为“声音嘶哑喷雾剂”的药品，这通常指代一类能缓解声嘶症状的咽喉喷雾剂。它们主要分为西药和中成药两大类，通过不同的成分和作用机理来缓解咽喉不适。

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

声音嘶哑喷雾剂是针对咽喉局部问题的快速缓解方案，选择时需区分中成药和西药成分，并严格遵守“对准、呼气、短期”的核心使用原则。**请注意，以上信息仅供参考，不能替代专业医疗建议。在初次使用任何药物前，特别是针对儿童或伴有其他疾病时，务必咨询医生或药师。**"""

# 原始 deepseek 引用(results),保留 url/title/snippet
RAW = [
    {"url": "https://www.catalog-taisho.com/content/dam/selfmedication/jp/ja/pabron/images/04695/pdf/04695_ProductPDF_cn.pdf", "title": "", "snippet": "Pabron咽喉喷雾365含有灭菌成分氯化十六烷基吡啶，不仅缓解咽喉炎症引起的咽喉部疼痛、肿胀等不适症状，也可缓解轻微的咽喉部不适感、声音嘶哑。仅需轻轻喷2～3次即可直接到达咽喉部，并发挥作用。带有柠檬薄荷醇味的清爽型使用感。"},
    {"url": "https://www.catalog-taisho.com/content/dam/selfmedication/jp/ja/pabron/images/04695/pdf/04695_ProductPDF_tw.pdf", "title": "", "snippet": "• 百保能喉嘴喷雾365含有殺菌成份十六烷基氯化吡啶，不仅適合喉發炎引起的喉痛、腫脹等不適症狀，還能舒緩輕微喉不適及聲音沙哑。 • 喷2-3次，就能直達喉發作用。 • 檸檬薄荷口味带来清爽使用感。"},
    {"url": "https://alinamin-kenko.jp/sc/products/kokuinko/benza_nodo.html", "title": "BENZA BLOCK 咽喉喷雾剂ベンザブロックのどスプレー", "snippet": "本剂有稍淡的薄荷醇味，可令口腔清爽舒畅。 功能 可缓解咽喉炎症引起的咽喉疼痛、咽喉肿胀、咽喉粗燥、咽喉不适、声音嘶哑"},
    {"url": "https://www.isodine.jp/wp-content/uploads/2021/02/attachment_nodo_cs.pdf", "title": "", "snippet": "功效及效果 适用于咽喉发炎导致的咽喉干涩、咽喉肿痛、咽喉不适、声音嘶哑等症状 用法及用量 每天数次，向咽喉粘膜上喷涂适量本品。"},
    {"url": "http://tampei.co.jp/products/foreign_language/pdf/kan/KOUNAKIZZU_%E7%B0%A1%E4%BD%93%E4%B8%AD%E6%96%87.pdf", "title": "", "snippet": "平息口腔内的炎症及疼痛的喷雾剂。葡萄味，让儿童易于使用。 功効 口腔炎、咽喉炎症引起的咽喉疼痛、咽干、咽喉肿痛、咽喉不适、声音嘶哑 用法用量 1天数次，将适量的药膏喷于患处。"},
    {"url": "https://www.ikedamohando.co.jp/sc/products/nodospray.html", "title": "ムヒののどスプレー：Nodo Spray（Oral mucosa SPRAY for Children）｜产品简介｜池田模范堂", "snippet": "针对儿童“喉咙痛”的配方 - 儿童喉咙痛的原因是伴有“感冒”、“大声叫喊后的声音嘶哑”等症状的喉咙“炎症”。"},
    {"url": "https://ae.iherb.com/pr/sovereign-silver-multi-symptom-sore-throat-spray-1-fl-oz-29-ml/146155", "title": "多症状喉咙痛舒缓喷雾，1 液量盎司（29 毫升）", "snippet": "缓解多症状喉部不适：缓解因咳嗽、着凉和声音过度使用引起的喉咙痛和轻微炎性反应。 不会造成麻木：缓解疼痛而不会带来麻木感。 产品用途：发红、干涩、喉咙痛和声音嘶哑。"},
    {"url": "https://www.daiichisankyo-hc.co.jp/cn/products/details/lulu_nodo_spray/", "title": "LULU throat spray |第一三共医药保健", "snippet": "使用本产品5至6天后，若症状仍未改善，请停止使用，并携带说明书咨询医生、药剂师或注册销售人员。 咽喉发炎引起的咽喉疼痛、咽喉肿胀、咽喉不适、咽喉刺激、声音嘶哑、口腔炎 每天多次喷洒适量于患处。"},
    {"url": "http://agri.nais.net.cn/patentdetails/69C940FF-9C55-4CF2-AD6C-E8401FBD3B1D.html", "title": "一种黄氏响声喷雾剂的制备方法农业专利-农业学术服务平台", "snippet": "本发明涉及一种黄氏响声喷雾剂的制备方法,以胖大海、蝉蜕、连翘、桔梗、甘草、大黄、川芎、诃子肉、浙贝母、薄荷为原料,具有疏风清热,化痰散结,利咽开音的功能,用于声音嘶哑,咽喉肿痛,咽干灼热,咽中有痰;急、慢性喉炎。"},
    {"url": "https://uy.iherb.com/pr/wishgarden-herbs-kick-ass-throat-spray-1-fl-oz-30-ml/116610", "title": "WishGarden Herbs, 喉咙舒缓喷雾，1 液量盎司（30 毫升）", "snippet": "声音嘶哑、说话困难或喉咙发炎、疲劳和干燥时，可服用本配方。本配方中的草本具有滋润和舒缓功效，有助于缓解季节性激发或过度使用带来的不适。"},
    {"url": "http://tampei.co.jp/products/foreign_language/pdf/han/KOUNAKIZZU_%E7%B9%81%E9%AB%94%E4%B8%AD%E6%96%87.pdf", "title": "", "snippet": "作為添加物，含有甘油、乙二胺四乙酸二鈉、D-山梨糖醇、糖精鈉、磷酸二氫鈉、碳酸氫鈉、氯化十六烷基、乙醇、香料。"},
    {"url": "https://drugs.dxy.cn/pc/drug/pPJGs_Hux-jhY9FoZrb2VaQ", "title": "贝可乐（丙酸倍氯米松吸入粉雾剂）", "snippet": "活性成分是二丙酸倍氯米松，是一种强效局部用糖皮质激素，能增强内皮细胞、平滑肌细胞和溶酶体膜的稳定性，抑制免疫反应和降低抗体合成。"},
]

cites = []
for i, c in enumerate(RAW):
    u = c["url"]
    cites.append({"url": u, "title": c["title"], "snippet": c["snippet"],
                  "domain": urlparse(u).netloc, "position": i + 1})

eng = create_engine(os.environ["DB_URL"])
with eng.begin() as conn:
    conn.execute(
        text("UPDATE browser_jobs SET status='done', answer=:a, citations_json=:c, "
             "source_url=:s, error=NULL, finished_at=:f WHERE id=:id"),
        {"a": ANSWER, "c": json.dumps(cites, ensure_ascii=False),
         "s": cites[0]["url"], "f": datetime.utcnow(), "id": JOB_ID},
    )
print(f"job {JOB_ID} updated: ans_len={len(ANSWER)} cites={len(cites)}")
