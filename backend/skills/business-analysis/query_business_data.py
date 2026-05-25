"""
DramaTalk 平台经营数据查询脚本

从 Doris 数仓查询指定月份的核心经营指标，输出 JSON 格式结果。
供 LLM 经营分析使用。

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


# 默认数据库配置（可通过环境变量或参数覆盖）
DEFAULT_CONFIG = {
    "host": os.environ.get("DORIS_HOST", "192.168.5.56"),
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


def query_recharge(conn, month: str) -> dict:
    """查询充值数据。"""
    start_date = f"{month}-01"
    # 计算下月第一天
    year, mon = int(month[:4]), int(month[5:7])
    if mon == 12:
        end_date = f"{year+1}-01-01"
    else:
        end_date = f"{year}-{mon+1:02d}-01"

    sql = f"""
    SELECT
        COUNT(*) as order_count,
        SUM(money) as total_amount,
        SUM(CASE WHEN recharge_type=0 THEN money ELSE 0 END) as recharge_amount,
        SUM(CASE WHEN recharge_type=1 THEN money ELSE 0 END) as subscribe_amount,
        SUM(CASE WHEN recharge_type=1 AND subscribe_renew=0 THEN money ELSE 0 END) as new_subscribe_amount,
        SUM(CASE WHEN recharge_type=1 AND subscribe_renew=1 THEN money ELSE 0 END) as renewal_amount,
        SUM(CASE WHEN type='APPLE' THEN money ELSE 0 END) as apple_amount,
        SUM(CASE WHEN type='GOOGLE' THEN money ELSE 0 END) as google_amount,
        COUNT(DISTINCT user_id) as paying_users,
        SUM(no_tax_money) as no_tax_total
    FROM dws_order
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    # 日维度充值趋势
    sql_daily = f"""
    SELECT DATE(create_time) as dt, SUM(money) as daily_amount, COUNT(*) as daily_count
    FROM dws_order
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
    GROUP BY DATE(create_time) ORDER BY dt
    """
    with conn.cursor() as cur:
        cur.execute(sql_daily)
        daily = cur.fetchall()

    return {
        "total_amount_usd": float(row["total_amount"] or 0),
        "order_count": int(row["order_count"] or 0),
        "recharge_amount_usd": float(row["recharge_amount"] or 0),
        "subscribe_amount_usd": float(row["subscribe_amount"] or 0),
        "new_subscribe_amount_usd": float(row["new_subscribe_amount"] or 0),
        "renewal_amount_usd": float(row["renewal_amount"] or 0),
        "apple_amount_usd": float(row["apple_amount"] or 0),
        "google_amount_usd": float(row["google_amount"] or 0),
        "paying_users": int(row["paying_users"] or 0),
        "no_tax_total_usd": float(row["no_tax_total"] or 0),
        "arpu": round(float(row["total_amount"] or 0) / max(int(row["paying_users"] or 1), 1), 2),
        "daily_trend": [{"date": str(d["dt"]), "amount": float(d["daily_amount"])} for d in daily],
    }


def query_new_users(conn, month: str) -> dict:
    """查询新增用户数据。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    sql = f"""
    SELECT COUNT(*) as new_user_count
    FROM dws_order
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND new_user = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    # 新用户充值转化
    sql_new_pay = f"""
    SELECT COUNT(DISTINCT user_id) as new_paying_users
    FROM dws_order
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND new_user = 1
    """
    with conn.cursor() as cur:
        cur.execute(sql_new_pay)
        pay_row = cur.fetchone()

    return {
        "new_user_orders": int(row["new_user_count"] or 0),
        "new_paying_users": int(pay_row["new_paying_users"] or 0),
    }


def query_game(conn, month: str) -> dict:
    """查询游戏消费数据。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    sql = f"""
    SELECT
        SUM(CASE WHEN action='gameBet' THEN amount ELSE 0 END) as total_bet,
        SUM(CASE WHEN action='gamePrize' THEN amount ELSE 0 END) as total_prize,
        COUNT(DISTINCT CASE WHEN action='gameBet' THEN identification END) as bet_users
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND action IN ('gameBet', 'gamePrize')
      AND currency = 'bean'
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    # 各游戏分布
    sql_games = f"""
    SELECT
        object_id,
        SUM(CASE WHEN action='gameBet' THEN amount ELSE 0 END) as bet_amount,
        SUM(CASE WHEN action='gamePrize' THEN amount ELSE 0 END) as prize_amount
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND action IN ('gameBet', 'gamePrize')
      AND currency = 'bean'
    GROUP BY object_id
    ORDER BY bet_amount DESC
    """
    game_name_map = {"1004": "TP", "1030": "SP", "1018": "CQ", "1025": "GD"}
    with conn.cursor() as cur:
        cur.execute(sql_games)
        games = cur.fetchall()

    game_detail = []
    for g in games:
        oid = str(g["object_id"]) if g["object_id"] else "other"
        game_detail.append({
            "game": game_name_map.get(oid, f"其他({oid})"),
            "bet_amount": int(g["bet_amount"] or 0),
            "prize_amount": int(g["prize_amount"] or 0),
            "net_revenue": int((g["bet_amount"] or 0) - (g["prize_amount"] or 0)),
        })

    return {
        "total_bet_beans": int(row["total_bet"] or 0),
        "total_prize_beans": int(row["total_prize"] or 0),
        "net_revenue_beans": int((row["total_bet"] or 0) - (row["total_prize"] or 0)),
        "bet_users": int(row["bet_users"] or 0),
        "game_detail": game_detail,
    }


def query_gift(conn, month: str) -> dict:
    """查询送礼数据。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    sql = f"""
    SELECT
        SUM(CASE WHEN action='gifting' THEN amount ELSE 0 END) as send_beans,
        SUM(CASE WHEN action='giftingIncome' THEN amount ELSE 0 END) as received_gems,
        COUNT(DISTINCT CASE WHEN action='gifting' THEN identification END) as send_users
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND action IN ('gifting', 'giftingIncome')
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    return {
        "send_beans": int(row["send_beans"] or 0),
        "received_gems": int(row["received_gems"] or 0),
        "send_users": int(row["send_users"] or 0),
    }


def query_reel(conn, month: str) -> dict:
    """查询短剧消费数据。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    sql = f"""
    SELECT
        SUM(amount) as total_reel_spend,
        COUNT(DISTINCT identification) as reel_users,
        COUNT(*) as reel_transactions
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
      AND action = 'reelPurchase'
      AND currency = 'bean'
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    return {
        "total_spend_beans": int(row["total_reel_spend"] or 0),
        "reel_users": int(row["reel_users"] or 0),
        "transactions": int(row["reel_transactions"] or 0),
        "avg_spend_per_user": round(
            int(row["total_reel_spend"] or 0) / max(int(row["reel_users"] or 1), 1)
        ),
    }


def query_active_users(conn, month: str) -> dict:
    """查询活跃用户数据。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    # MAU: 月内有任意操作的去重用户数
    sql_mau = f"""
    SELECT COUNT(DISTINCT identification) as mau
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
    """
    with conn.cursor() as cur:
        cur.execute(sql_mau)
        mau_row = cur.fetchone()

    # DAU 趋势
    sql_dau = f"""
    SELECT DATE(create_time) as dt, COUNT(DISTINCT identification) as dau
    FROM dws_wallet_operation
    WHERE create_time >= '{start_date}' AND create_time < '{end_date}'
    GROUP BY DATE(create_time) ORDER BY dt
    """
    with conn.cursor() as cur:
        cur.execute(sql_dau)
        dau_rows = cur.fetchall()

    dau_list = [int(d["dau"]) for d in dau_rows]
    avg_dau = round(sum(dau_list) / max(len(dau_list), 1))

    return {
        "mau": int(mau_row["mau"] or 0),
        "avg_dau": avg_dau,
        "max_dau": max(dau_list) if dau_list else 0,
        "min_dau": min(dau_list) if dau_list else 0,
        "dau_mau_ratio": round(avg_dau / max(int(mau_row["mau"] or 1), 1), 3),
        "dau_trend": [{"date": str(d["dt"]), "dau": int(d["dau"])} for d in dau_rows],
    }


def query_revenue_summary(conn, month: str) -> dict:
    """查询收入汇总（从 dws_total_revenue_daily）。"""
    start_date = f"{month}-01"
    year, mon = int(month[:4]), int(month[5:7])
    end_date = f"{year}-{mon+1:02d}-01" if mon < 12 else f"{year+1}-01-01"

    sql = f"""
    SELECT
        SUM(recharge_amount) as recharge_amount,
        SUM(subscribe_amount) as subscribe_amount,
        SUM(ad_amount) as ad_amount,
        SUM(promotion_cost) as promotion_cost,
        SUM(withdraws_cost) as withdraws_cost
    FROM dws_total_revenue_daily
    WHERE `date` >= '{start_date}' AND `date` < '{end_date}'
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()

    recharge = float(row["recharge_amount"] or 0)
    subscribe = float(row["subscribe_amount"] or 0)
    ad = float(row["ad_amount"] or 0)
    promotion = float(row["promotion_cost"] or 0)
    withdraws = float(row["withdraws_cost"] or 0)

    return {
        "recharge_amount_usd": recharge,
        "subscribe_amount_usd": subscribe,
        "ad_amount_usd": ad,
        "total_revenue_usd": round(recharge + subscribe + ad, 2),
        "promotion_cost_usd": promotion,
        "withdraws_cost_usd": withdraws,
        "net_revenue_usd": round(recharge + subscribe + ad - promotion - withdraws, 2),
    }


def main():
    """主函数：解析参数，查询数据，输出 JSON。"""
    parser = argparse.ArgumentParser(description="DramaTalk 经营数据查询")
    parser.add_argument(
        "--month", required=True,
        help="查询月份，格式 YYYY-MM（如 2026-04）"
    )
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

    # 查询数据
    try:
        conn = get_connection(config)
        result = {
            "month": args.month,
            "query_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "recharge": query_recharge(conn, args.month),
            "new_users": query_new_users(conn, args.month),
            "game": query_game(conn, args.month),
            "gift": query_gift(conn, args.month),
            "reel": query_reel(conn, args.month),
            "active_users": query_active_users(conn, args.month),
            "revenue_summary": query_revenue_summary(conn, args.month),
        }
        conn.close()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
