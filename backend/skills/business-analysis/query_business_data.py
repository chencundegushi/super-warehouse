"""
DramaTalk 平台经营数据查询脚本

查询指定月份的核心经营指标（含上月环比数据），输出 JSON 格式。
支持大盘总览 + 分包（DT/DTL）维度。

使用方式:
    python query_business_data.py --month 2026-04
    python query_business_data.py --month 2026-04 --host 192.168.10.253
"""

import argparse
import json
import os
import sys
from datetime import datetime

import pymysql


DEFAULT_CONFIG = {
    "host": os.environ.get("DORIS_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DORIS_PORT", "3308")),
    "user": os.environ.get("DORIS_USER", "dramatalk_report"),
    "password": os.environ.get("DORIS_PASSWORD", "dramatalk_report"),
    "database": "dt",
}


def get_connection(config: dict):
    """获取数据库连接。"""
    return pymysql.connect(
        host=config["host"],
        port=config["port"],
        user=config["user"],
        password=config["password"],
        database=config["database"],
        charset="utf8mb4",
        connect_timeout=10,
        read_timeout=60,
        cursorclass=pymysql.cursors.DictCursor,
    )


def month_range(month: str) -> tuple[str, str]:
    """返回月份的起止日期。"""
    year, mon = int(month[:4]), int(month[5:7])
    start = f"{year}-{mon:02d}-01"
    if mon == 12:
        end = f"{year + 1}-01-01"
    else:
        end = f"{year}-{mon + 1:02d}-01"
    return start, end


def prev_month(month: str) -> str:
    """返回上一个月份字符串。"""
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 1:
        return f"{year - 1}-12"
    return f"{year}-{mon - 1:02d}"


def query_overview(conn, month: str) -> dict:
    """查询大盘核心指标（全包汇总）。"""
    start, end = month_range(month)

    # 充值数据
    sql_recharge = f"""
    SELECT
        SUM(money) as total_recharge,
        SUM(no_tax_money) as no_tax_recharge,
        SUM(CASE WHEN recharge_type=0 THEN money ELSE 0 END) as coin_recharge,
        SUM(CASE WHEN recharge_type=1 THEN money ELSE 0 END) as subscribe_recharge,
        COUNT(DISTINCT user_id) as paying_users
    FROM dws_order
    WHERE create_time >= '{start}' AND create_time < '{end}'
    """
    with conn.cursor() as cur:
        cur.execute(sql_recharge)
        r = cur.fetchone()

    # 消耗数据（游戏、送礼、短剧）
    sql_consume = f"""
    SELECT
        SUM(CASE WHEN action='gameBet' AND currency='bean' THEN amount ELSE 0 END) as game_bet,
        SUM(CASE WHEN action='gamePrize' AND currency='bean' THEN amount ELSE 0 END) as game_prize,
        SUM(CASE WHEN action='gifting' THEN amount ELSE 0 END) as gift_send,
        SUM(CASE WHEN action='giftingIncome' THEN amount ELSE 0 END) as gift_receive,
        SUM(CASE WHEN action='reelPurchase' AND currency='bean' THEN amount ELSE 0 END) as reel_spend,
        COUNT(DISTINCT identification) as mau
    FROM dws_wallet_operation
    WHERE create_time >= '{start}' AND create_time < '{end}'
    """
    with conn.cursor() as cur:
        cur.execute(sql_consume)
        c = cur.fetchone()

    # 投放成本（从 dws_total_revenue_daily）
    sql_cost = f"""
    SELECT
        SUM(promotion_cost) as promotion_cost,
        SUM(recharge_amount) as rev_recharge,
        SUM(subscribe_amount) as rev_subscribe
    FROM dws_total_revenue_daily
    WHERE `date` >= '{start}' AND `date` < '{end}'
    """
    with conn.cursor() as cur:
        cur.execute(sql_cost)
        cost = cur.fetchone()

    total_recharge = float(r["total_recharge"] or 0)
    promotion_cost = float(cost["promotion_cost"] or 0)
    game_bet = int(c["game_bet"] or 0)
    gift_send = int(c["gift_send"] or 0)
    reel_spend = int(c["reel_spend"] or 0)

    return {
        "total_recharge_usd": total_recharge,
        "no_tax_recharge_usd": float(r["no_tax_recharge"] or 0),
        "coin_recharge_usd": float(r["coin_recharge"] or 0),
        "subscribe_recharge_usd": float(r["subscribe_recharge"] or 0),
        "paying_users": int(r["paying_users"] or 0),
        "game_bet_beans": game_bet,
        "game_prize_beans": int(c["game_prize"] or 0),
        "game_net_beans": game_bet - int(c["game_prize"] or 0),
        "gift_send_beans": gift_send,
        "gift_receive_gems": int(c["gift_receive"] or 0),
        "reel_spend_beans": reel_spend,
        "total_consume_beans": game_bet + gift_send + reel_spend,
        "mau": int(c["mau"] or 0),
        "promotion_cost_usd": promotion_cost,
        "roi": round(total_recharge / max(promotion_cost, 1), 2),
    }


def query_by_package(conn, month: str) -> dict:
    """查询分包数据（DT 和 DTL）。"""
    start, end = month_range(month)

    # 分包充值
    sql_recharge = f"""
    SELECT
        project_code,
        SUM(money) as total_recharge,
        SUM(CASE WHEN recharge_type=0 THEN money ELSE 0 END) as coin_recharge,
        SUM(CASE WHEN recharge_type=1 THEN money ELSE 0 END) as subscribe_recharge,
        COUNT(DISTINCT user_id) as paying_users
    FROM dws_order
    WHERE create_time >= '{start}' AND create_time < '{end}'
    GROUP BY project_code
    """
    with conn.cursor() as cur:
        cur.execute(sql_recharge)
        recharge_rows = cur.fetchall()

    # 分包消耗
    sql_consume = f"""
    SELECT
        project_code,
        SUM(CASE WHEN action='gameBet' AND currency='bean' THEN amount ELSE 0 END) as game_bet,
        SUM(CASE WHEN action='gamePrize' AND currency='bean' THEN amount ELSE 0 END) as game_prize,
        SUM(CASE WHEN action='gifting' THEN amount ELSE 0 END) as gift_send,
        SUM(CASE WHEN action='reelPurchase' AND currency='bean' THEN amount ELSE 0 END) as reel_spend,
        COUNT(DISTINCT identification) as active_users
    FROM dws_wallet_operation
    WHERE create_time >= '{start}' AND create_time < '{end}'
    GROUP BY project_code
    """
    with conn.cursor() as cur:
        cur.execute(sql_consume)
        consume_rows = cur.fetchall()

    # 分包投放成本
    sql_cost = f"""
    SELECT
        project_code,
        SUM(promotion_cost) as promotion_cost
    FROM dws_total_revenue_daily
    WHERE `date` >= '{start}' AND `date` < '{end}'
    GROUP BY project_code
    """
    with conn.cursor() as cur:
        cur.execute(sql_cost)
        cost_rows = cur.fetchall()

    # 组装结果
    recharge_map = {row["project_code"]: row for row in recharge_rows}
    consume_map = {row["project_code"]: row for row in consume_rows}
    cost_map = {row["project_code"]: row for row in cost_rows}

    result = {}
    for pkg in ["DT", "DTL"]:
        r = recharge_map.get(pkg, {})
        c = consume_map.get(pkg, {})
        co = cost_map.get(pkg, {})

        total_recharge = float(r.get("total_recharge") or 0)
        promotion_cost = float(co.get("promotion_cost") or 0)
        game_bet = int(c.get("game_bet") or 0)
        gift_send = int(c.get("gift_send") or 0)
        reel_spend = int(c.get("reel_spend") or 0)

        result[pkg] = {
            "total_recharge_usd": total_recharge,
            "coin_recharge_usd": float(r.get("coin_recharge") or 0),
            "subscribe_recharge_usd": float(r.get("subscribe_recharge") or 0),
            "paying_users": int(r.get("paying_users") or 0),
            "game_bet_beans": game_bet,
            "game_prize_beans": int(c.get("game_prize") or 0),
            "game_net_beans": game_bet - int(c.get("game_prize") or 0),
            "gift_send_beans": gift_send,
            "reel_spend_beans": reel_spend,
            "total_consume_beans": game_bet + gift_send + reel_spend,
            "active_users": int(c.get("active_users") or 0),
            "promotion_cost_usd": promotion_cost,
            "roi": round(total_recharge / max(promotion_cost, 1), 2),
        }

    return result


def query_game_detail(conn, month: str) -> dict:
    """查询各游戏投注明细（分包+分游戏）。"""
    start, end = month_range(month)

    sql = f"""
    SELECT
        project_code,
        object_id,
        SUM(CASE WHEN action='gameBet' THEN amount ELSE 0 END) as bet,
        SUM(CASE WHEN action='gamePrize' THEN amount ELSE 0 END) as prize
    FROM dws_wallet_operation
    WHERE create_time >= '{start}' AND create_time < '{end}'
      AND action IN ('gameBet', 'gamePrize')
      AND currency = 'bean'
    GROUP BY project_code, object_id
    ORDER BY bet DESC
    """
    game_names = {"1004": "TP", "1030": "SP", "1018": "CQ", "1025": "GD"}

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall()

    result = {"DT": [], "DTL": []}
    for row in rows:
        pkg = row["project_code"] or "DT"
        oid = str(row["object_id"]) if row["object_id"] else "other"
        entry = {
            "game": game_names.get(oid, f"其他({oid})"),
            "bet_beans": int(row["bet"] or 0),
            "prize_beans": int(row["prize"] or 0),
            "net_beans": int((row["bet"] or 0) - (row["prize"] or 0)),
        }
        if pkg in result:
            result[pkg].append(entry)

    return result


def main():
    """主函数：查询当月+上月数据，输出完整 JSON。"""
    parser = argparse.ArgumentParser(description="DramaTalk 经营数据查询")
    parser.add_argument("--month", required=True, help="查询月份 YYYY-MM")
    parser.add_argument("--host", default=None, help="Doris 地址")
    parser.add_argument("--port", type=int, default=None, help="Doris 端口")
    parser.add_argument("--user", default=None, help="Doris 用户")
    parser.add_argument("--password", default=None, help="Doris 密码")
    args = parser.parse_args()

    # 校验月份格式
    try:
        datetime.strptime(args.month, "%Y-%m")
    except ValueError:
        print(json.dumps({"error": f"月份格式错误: {args.month}，应为 YYYY-MM"}))
        sys.exit(1)

    # 构建配置
    config = DEFAULT_CONFIG.copy()
    if args.host:
        config["host"] = args.host
    if args.port:
        config["port"] = args.port
    if args.user:
        config["user"] = args.user
    if args.password:
        config["password"] = args.password

    # 计算上月
    prev = prev_month(args.month)

    try:
        conn = get_connection(config)

        result = {
            "month": args.month,
            "prev_month": prev,
            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "overview": query_overview(conn, args.month),
            "overview_prev": query_overview(conn, prev),
            "by_package": query_by_package(conn, args.month),
            "by_package_prev": query_by_package(conn, prev),
            "game_detail": query_game_detail(conn, args.month),
        }

        conn.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))

    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()