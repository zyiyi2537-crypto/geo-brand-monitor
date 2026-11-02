// 时间显示工具 —— 后端时间戳是 UTC(naive,无时区标记),用户在北京。
// 统一按 UTC 解析 → 转北京(Asia/Shanghai)显示,避免差 8 小时。

/**
 * 把后端的时间戳(ISO 字符串,可能是 naive UTC 无 Z)格式化成北京时间显示。
 * @param s 时间字符串(如 "2026-06-11T02:21:27" 或带 Z/+08:00)
 * @param withSeconds 是否显示秒(默认 true)
 * 返回 "YYYY-MM-DD HH:mm[:ss]";解析失败回退原串。
 */
export function fmtTime(s?: string | null, withSeconds = true): string {
  if (!s) return '';
  // 后端发的是 naive UTC(无时区标记)→ 补 Z 标记成 UTC;已带时区的(Z/+/-）原样
  const hasTz = /[Zz]$|[+-]\d{2}:?\d{2}$/.test(s);
  const d = new Date(hasTz ? s : s + 'Z');
  if (isNaN(d.getTime())) return s.replace('T', ' ').slice(0, withSeconds ? 19 : 16);
  const fmt = new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    hour12: false,
  });
  // Intl 输出形如 "2026/06/11 10:21:27" → 统一成 "2026-06-11 10:21:27"
  return fmt.format(d).replace(/\//g, '-');
}
