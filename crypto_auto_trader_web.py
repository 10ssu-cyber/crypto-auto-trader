# ✅ 기존 자동매매 웹 대시보드에 하락장 대응 전략 통합
import pyupbit
import time
import threading
import numpy as np
import pandas as pd
from flask import Flask, render_template_string, request, jsonify
from datetime import datetime
import os

app = Flask(__name__)

access = "77zlU8lmsthxN0Q9z5YI8Vl0YrANFLU8rGfhMbIH"
secret = "syN0DmD4jgqX5rzFx0UYuCWo5jOxKUIJ0URu6xAq"
upbit = pyupbit.Upbit(access, secret)

tickers = pyupbit.get_tickers(fiat="KRW")
states = {
    t: {"holding": False, "buy_price": 0, "log": [], "profit": 0.0, "history": []} for t in tickers
}

balances = upbit.get_balances()
for b in balances:
    symbol = b.get('currency')
    if symbol and symbol != 'KRW':
        ticker = f"KRW-{symbol}"
        if ticker in states and float(b.get('balance', 0)) > 0:
            states[ticker]['holding'] = True
            states[ticker]['buy_price'] = float(b.get('avg_buy_price', 0))


def get_indicators(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="minute1", count=100)
    if df is None or len(df) < 60:
        return None

    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(window=14).mean()
    avg_loss = loss.rolling(window=14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))

    ema12 = df['close'].ewm(span=12).mean()
    ema26 = df['close'].ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9).mean()

    ma20 = df['close'].rolling(window=20).mean()
    std20 = df['close'].rolling(window=20).std()
    df['upper'] = ma20 + (2 * std20)
    df['lower'] = ma20 - (2 * std20)

    df['ma20'] = df['close'].rolling(window=20).mean()
    df['ma60'] = df['close'].rolling(window=60).mean()

    df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
    return df


def should_buy(df):
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    return (
        latest['rsi'] < 35 and
        latest['macd'] > latest['signal'] and
        latest['close'] < latest['lower'] and
        latest['obv'] > prev['obv'] and
        latest['close'] < latest['ma20'] * 0.985 and
        latest['ma20'] > latest['ma60']
    )


def should_sell(df, buy_price):
    latest = df.iloc[-1]
    profit_ratio = (latest['close'] - buy_price) / buy_price

    return (
        profit_ratio <= -0.02 or
        latest['macd'] < latest['signal'] or
        latest['rsi'] > 55 and latest['macd'] < latest['signal']
    )


def trade_bot():
    while True:
        for ticker in tickers:
            try:
                df = get_indicators(ticker)
                print(f"[체크] {ticker} 데이터 확인 중")
                if df is None:
                    continue

                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                current_price = pyupbit.get_current_price(ticker)
                if current_price:
                    states[ticker]['history'].append(current_price)

                if not states[ticker]['holding'] and should_buy(df):
                    order = upbit.buy_market_order(ticker, 10000)
                    print(f"[매수 요청] {ticker} - {current_price}")
                    states[ticker]['holding'] = True
                    states[ticker]['buy_price'] = current_price
                    states[ticker]['log'].append(f"[{now}] ✅ 매수: {ticker} @ {current_price}")

                elif states[ticker]['holding'] and should_sell(df, states[ticker]['buy_price']):
                    balance = upbit.get_balance(ticker)
                    if balance > 0:
                        order = upbit.sell_market_order(ticker, balance)
                        print(f"[매도 요청] {ticker} - {current_price}")
                        profit = (current_price - states[ticker]['buy_price']) / states[ticker]['buy_price'] * 100
                        states[ticker]['profit'] += profit
                        states[ticker]['holding'] = False
                        states[ticker]['buy_price'] = 0
                        states[ticker]['log'].append(f"[{now}] ✅ 매도: {ticker} @ {current_price} | 수익률: {profit:.2f}%")
            except Exception as e:
                states[ticker]['log'].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 오류: {ticker} - {str(e)}")
        time.sleep(60)


@app.route("/")
def index():
    ticker = request.args.get("ticker", "KRW-BTC")
    state = states[ticker]
    return render_template_string("""
    <html><head><meta charset='utf-8'><title>KRW 코인 자동매매</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js'></script></head>
    <body style="background:#111;color:#eee;font-family:sans-serif;padding:20px;">
    <h1 style="color:#50fa7b">📈 KRW 코인 자동매매 대시보드</h1>
    <div style="margin-bottom:20px">보유 상태: <strong>{{ '보유 중' if state.holding else '미보유' }}</strong><br>
    최근 매수 가격: {{ state.buy_price }}<br>
    마지막 로그: {{ state.log[-1] if state.log else '없음' }}</div>
    <div style="margin-bottom:10px"><strong>수익률: {{ '%.2f' % (state.profit if state.profit else 0.0) }}%</strong></div>
    <div style='margin: 40px 0;'>
    <canvas id="priceChart" width="1000" height="280"></canvas>
    </div>
    <h2>최근 로그</h2><ul>
    {% for entry in state.log[-10:] %}<li>{{ entry }}</li>{% endfor %}
    </ul>
    <h3>코인 선택</h3>
    <table style='margin-bottom:30px;border-collapse:collapse;'>
      <tr>
      {% for t in tickers %}
        <td style='padding:4px 10px;'>
          <a href='/?ticker={{t}}' style='color:{% if states[t].holding %}#ff6b6b{% elif t==ticker %}#50fa7b{% else %}#ccc{% endif %}; text-decoration:none;'>{{t}}</a>
        </td>
        {% if loop.index % 10 == 0 %}</tr><tr>{% endif %}
      {% endfor %}
      </tr>
    </table>
    <script>
    fetch("/price-data?ticker={{ ticker }}")
      .then(res => res.json()).then(data => {
        const labels = Array.from({length: data.length}, (_, i) => i + 1);
        new Chart(document.getElementById("priceChart"), {
          type: "line",
          data: { labels, datasets: [{ data: data, borderColor: "#50fa7b", tension: 0.2 }] },
          options: { scales: { x: { ticks: { color: "#999" } }, y: { ticks: { color: "#999" } } } }
        });
      });
    </script>
    </body></html>""", ticker=ticker, state=state, tickers=tickers, states=states)


@app.route("/price-data")
def price_data():
    ticker = request.args.get("ticker", "KRW-BTC")
    return jsonify(states[ticker]['history'][-60:])


if __name__ == "__main__":
    threading.Thread(target=trade_bot, daemon=True).start()
    PORT = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=PORT)
