# ✅ 기존 자동매매 웹 대시보드에 하락장 대응 전략 통합
import pyupbit
import time
import threading
import numpy as np
import pandas as pd
from flask import Flask, render_template_string, request
from datetime import datetime

app = Flask(__name__)

access = "77zlU8lmsthxN0Q9z5YI8Vl0YrANFLU8rGfhMbIH"
secret = "syN0DmD4jgqX5rzFx0UYuCWo5jOxKUIJ0URu6xAq"
upbit = pyupbit.Upbit(access, secret)

tickers = pyupbit.get_tickers(fiat="KRW")
states = {
    t: {"holding": False, "buy_price": 0, "log": [], "profit": 0.0} for t in tickers
}

# 실제 보유 종목 초기화
balances = upbit.get_balances()
for b in balances:
    symbol = b['currency']
    if symbol == 'KRW':
        continue
    ticker = f"KRW-{symbol}"
    if ticker in states and float(b['balance']) > 0:
        states[ticker]['holding'] = True
        states[ticker]['buy_price'] = float(b['avg_buy_price'])

def get_indicators(ticker):
    df = pyupbit.get_ohlcv(ticker, interval="minute5", count=100)
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

    # ✅ 반등 중인 흐름을 확인 후 여유 있게 매도
    # RSI가 50 이상이고 MACD가 하향 돌파할 때만 매도
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

                if not states[ticker]['holding'] and should_buy(df):
                    price = pyupbit.get_current_price(ticker)
                    order = upbit.buy_market_order(ticker, 10000)
                    print(f"[매수 요청] {ticker} - {price}")
                    states[ticker]['holding'] = True
                    states[ticker]['buy_price'] = price
                    states[ticker]['log'].append(f"[{now}] ✅ 매수: {ticker} @ {price}")

                elif states[ticker]['holding'] and should_sell(df, states[ticker]['buy_price']):
                    balance = upbit.get_balance(ticker)
                    if balance > 0:
                        price = pyupbit.get_current_price(ticker)
                        order = upbit.sell_market_order(ticker, balance)
                        print(f"[매도 요청] {ticker} - {price}")
                        profit = (price - states[ticker]['buy_price']) / states[ticker]['buy_price'] * 100
                        states[ticker]['profit'] += profit
                        states[ticker]['holding'] = False
                        states[ticker]['buy_price'] = 0
                        states[ticker]['log'].append(f"[{now}] ✅ 매도: {ticker} @ {price} | 수익률: {profit:.2f}%")
            except Exception as e:
                states[ticker]['log'].append(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ 오류: {ticker} - {str(e)}")
        time.sleep(60)

@app.route("/")
def index():
    ticker = request.args.get("ticker", "KRW-BTC")
    state = states[ticker]
    return render_template_string("""
    <html><head><meta charset='utf-8'><title>KRW 코인 자동매매</title>
    <script src='https://cdn.jsdelivr.net/npm/chart.js'></script>
</head>
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
    <td style='padding:6px 12px; border: 1px solid #444; background-color:{% if states[t].holding %}#331111{% elif t==ticker %}#133113{% else %}#1e1e1e{% endif %};'>
      <a href='/?ticker={{t}}' style='color:{% if states[t].holding %}#ff6b6b{% elif t==ticker %}#50fa7b{% else %}#ccc{% endif %}; text-decoration:none; font-weight: {% if states[t].holding or t==ticker %}bold{% else %}normal{% endif %};'>{{t}}</a>
    </td>
    {% if loop.index % 10 == 0 %}</tr><tr>{% endif %}
  {% endfor %}
  </tr>
</table>
    <script>
    const chartCanvas = document.getElementById("priceChart");
let chart;

function fetchAndUpdateChart() {
  fetch("https://api.upbit.com/v1/candles/minutes/1?market={{ ticker | urlencode }}&count=60")
    .then(res => res.json()).then(data => {
      const labels = data.map(d => d.candle_date_time_kst.slice(11,16)).reverse();
      const prices = data.map(d => d.trade_price).reverse();
      const buyIndex = prices.findIndex(p => p === {{ state.buy_price }});
      const buys = prices.map((_, i) => i === buyIndex ? {{ state.buy_price }} : null);
      const chartData = {
        labels,
        datasets: [
          {
            label: 'Take Profit',
            data: prices.map(() => {{ state.buy_price }} * 1.0125),
            borderColor: "#77dd77",
            borderWidth: 1,
            borderDash: [2, 4],
            fill: false,
            tension: 0,
            pointRadius: 0
          },
          {
            label: 'Stop Loss',
            data: prices.map(() => {{ state.buy_price }} * 0.9925),
            borderColor: "#ff7777",
            borderWidth: 1,
            borderDash: [2, 4],
            fill: false,
            tension: 0,
            pointRadius: 0
          },
          {
            label: 'Price',
            data: prices,
            borderColor: "#50fa7b",
            tension: 0.2
          },
          {
            label: 'Buy Price (Line)',
            data: prices.map(() => {{ state.buy_price }}),
            borderColor: "#ff6b6b",
            borderDash: [5, 5],
            fill: false,
            tension: 0,
            pointRadius: 0
          },
          {
            label: 'Buy Point',
            data: buys,
            borderColor: "#ff6b6b",
            pointRadius: 6,
            pointBackgroundColor: "#ff6b6b",
            showLine: false
          }
        ]
      };

      if (chart) {
        chart.data = chartData;
        chart.update();
      } else {
        chart = new Chart(chartCanvas, {
          type: "line",
          data: chartData,
          options: {
            scales: {
              x: { ticks: { color: "#999" } },
              y: {
              ticks: { color: "#999" },
              min: Math.min(...prices),
              max: Math.max(...prices)
            }
            }
          }
        });
      }
    });
}

fetchAndUpdateChart();
setInterval(fetchAndUpdateChart, 30000);
</script>
  </body></html>""", ticker=ticker, state=state, tickers=tickers, states=states)

if __name__ == "__main__":
    threading.Thread(target=trade_bot, daemon=True).start()
    app.run(debug=False, port=5050)
