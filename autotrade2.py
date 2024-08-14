import os
from dotenv import load_dotenv
load_dotenv()
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.cm_futures import CMFutures
import pandas as pd
import pandas_ta as ta
import json
from openai import OpenAI
import schedule
import time
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta

# Setup
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
binance = Client(os.getenv("BINANCE_ACCESS"), os.getenv("BINANCE_SECRET"))
cm_futures_client = CMFutures()
current_time = cm_futures_client.time()
current_time = current_time['serverTime']
# 시간설정
def milliseconds_to_date(ms):
    seconds = ms / 1000.0
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return dt.strftime('%Y-%m-%d %H:%M:%S'), dt

def subtract_weeks(date, weeks):
    new_date = date - timedelta(weeks=weeks)
    return new_date.strftime('%Y-%m-%d %H:%M:%S')

def subtract_months(date, months):
    new_date = date - relativedelta(months=months)
    return new_date.strftime('%Y-%m-%d %H:%M:%S')

def subtract_days(date, days):
    new_date = date - timedelta(days=days)
    return new_date.strftime('%Y-%m-%d %H:%M:%S')

formatted_date, date_obj = milliseconds_to_date(current_time)
weeks_date = subtract_weeks(date_obj, 2)
month_date = subtract_months(date_obj, 1)
week_date = subtract_weeks(date_obj, 1)
day_date = subtract_days(date_obj, 3)

#심볼 설정
symbol = 'BTCUSDT'

balances = binance.futures_account_balance()
for b in balances:
    if b['asset'] == "USDT":
        usdt_balance = b['availableBalance']

def get_current_status():
    orderbook = binance.futures_order_book(symbol="BTCUSDT")
    current_time = cm_futures_client.time()
    usdt_balance = 0
    notional_value = 0
    btc_entryprice = 0
    balances = binance.futures_account_balance()
    position = binance.futures_position_information(symbol='BTCUSDT')
    for b in balances:
        if b['asset'] == "USDT":
            usdt_balance = b['availableBalance']
    for p in position:
        if p['symbol'] == 'BTCUSDT':
            btc_entryprice = p['entryPrice']
            notional_value = p['notional']

    current_status = {'current_time': current_time, 'orderbook': orderbook, 'notional_value': notional_value, 'usdt_balance': usdt_balance, 'btc_entryprice': btc_entryprice}
    return json.dumps(current_status)


def fetch_and_prepare_data():
    # Fetch data
    #daily = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '1d', start_str = str(month_date))
    f_hourly = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '4h', start_str = str(month_date))
    hourly = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '1h', start_str = str(week_date))
    #minutes = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '15m', start_str = str(day_date))

    def filter_indices(data):
        indices_to_keep = [0, 1, 2, 3, 4, 5, 7]
        indices_to_keep = set(indices_to_keep)

        filtered_data = []
        for sublist in data:
            filtered_sublist = [item for idx, item in enumerate(sublist) if idx in indices_to_keep]
            filtered_data.append(filtered_sublist)
    
        return filtered_data

    #daily = filter_indices(daily)
    f_hourly = filter_indices(f_hourly)
    hourly = filter_indices(hourly)
    #minutes = filter_indices(minutes)

    #df_daily = pd.DataFrame(daily, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    df_f_hourly = pd.DataFrame(f_hourly, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    df_hourly = pd.DataFrame(hourly, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    #df_minutes = pd.DataFrame(minutes, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])

    def convert_dataframe_values_to_numeric(df):
      for column in df.columns:
          df[column] = pd.to_numeric(df[column], errors='coerce')
      return df

    #df_daily = convert_dataframe_values_to_numeric(df_daily)
    df_f_hourly= convert_dataframe_values_to_numeric(df_f_hourly)
    df_hourly = convert_dataframe_values_to_numeric(df_hourly)
    #df_minutes = convert_dataframe_values_to_numeric(df_minutes)
    
    # Define a helper function to add indicators
    def add_indicators(df):
        # RSI
        df['RSI_14'] = ta.rsi(df['Close'], length=14)

        return df

    # Add indicators to both dataframes
    #df_daily = add_indicators(df_daily)
    df_f_hourly = add_indicators(df_f_hourly)
    df_hourly = add_indicators(df_hourly)
    #df_minutes = add_indicators(df_minutes)

    combined_df = pd.concat([df_f_hourly, df_hourly], keys=['f_hourly', 'hourly'])
    combined_data = combined_df.to_json(orient='split')

    # make combined data as string and print length
    print(len(combined_data))

    return json.dumps(combined_data)

def get_instructions(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as file:
            instructions = file.read()
        return instructions
    except FileNotFoundError:
        print("File not found.")
    except Exception as e:
        print("An error occurred while reading the file:", e)

def analyze_data_with_gpt4(data_json):
    instructions_path = "instructions.md"
    try:
        instructions = get_instructions(instructions_path)
        if not instructions:
            print("No instructions found.")
            return None

        current_status = get_current_status()
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": data_json},
                {"role": "user", "content": current_status}
            ],
            response_format={"type":"json_object"}
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in analyzing data with GPT-4: {e}")
        return None

def execute_buy():
    print("Attempting to buy BTCUSDT...")
    try:
        if float(usdt_balance) > 20:
            result = binance.futures_create_order(symbol = "BTCUSDT", type= "MARKET", side = 'BUY', quantity = 0.02)
            print("Buy order successful:", result)
    except Exception as e:
        print(f"Failed to execute buy order: {e}")

def execute_sell():
    print("Attempting to sell BTC...")
    try:
        if float(usdt_balance) > 20:
            result = binance.futures_create_order(symbol = "BTCUSDT", type= "MARKET", side = 'SELL', quantity = 0.02)
            print("Sell order successful:", result)
    except Exception as e:
        print(f"Failed to execute sell order: {e}")

def make_decision_and_execute():
    print("Making decision and executing...")
    data_json = fetch_and_prepare_data()
    advice = analyze_data_with_gpt4(data_json)

    try:
        decision = json.loads(advice)
        print(decision)
        if decision.get('decision') == "buy":
            execute_buy()
        elif decision.get('decision') == "sell":
            execute_sell()
    except Exception as e:
        print(f"Failed to parse the advice as JSON: {e}")

if __name__ == "__main__":
    make_decision_and_execute()
    schedule.every().hour.at(":01").do(make_decision_and_execute)

    while True:
        schedule.run_pending()
        time.sleep(1)