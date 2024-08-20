import os
from dotenv import load_dotenv
load_dotenv()
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.cm_futures import CMFutures
from datetime import datetime, timezone, timedelta
from dateutil.relativedelta import relativedelta
import pandas as pd
import pandas_ta as ta
import json
from openai import OpenAI
import schedule
import time
import requests
import sqlite3

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

def initialize_db(db_path='trading_decisions.sqlite'):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                decision TEXT,
                percentage REAL,
                reason TEXT,
                notional_value REAL,
                usdt_balance REAL,
                btc_entryprice REAL,
                btcusdt_price REAL
            );
        ''')
        conn.commit()

def save_decision_to_db(decision, current_status):
    db_path = 'trading_decisions.sqlite'
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
    
        # Parsing current_status from JSON to Python dict
        status_dict = json.loads(current_status)
        current_price = binance.futures_order_book(symbol="BTCUSDT")['bids'][0][0]

        
        # Preparing data for insertion
        data_to_insert = (
            decision.get('decision'),
            decision.get('percentage', 100),  # Defaulting to 100 if not provided
            decision.get('reason', ''),  # Defaulting to an empty string if not provided
            status_dict.get('notional_value'),
            status_dict.get('usdt_balance'),
            status_dict.get('btc_entryprice'),
            current_price
        )
        
        # Inserting data into the database
        cursor.execute('''
            INSERT INTO decisions (timestamp, decision, percentage, reason, notional_value, usdt_balance, btc_entryprice, btcusdt_price)
            VALUES (datetime('now', 'localtime'), ?, ?, ?, ?, ?, ?, ?)
        ''', data_to_insert)
    
        conn.commit()

def fetch_last_decisions(db_path='trading_decisions.sqlite', num_decisions=50):
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp, decision, percentage, reason, notional_value, usdt_balance, btc_entryprice FROM decisions
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (num_decisions,))
        decisions = cursor.fetchall()

        if decisions:
            formatted_decisions = []
            for decision in decisions:
                # Converting timestamp to milliseconds since the Unix epoch
                ts = datetime.strptime(decision[0], "%Y-%m-%d %H:%M:%S")
                ts_millis = int(ts.timestamp() * 1000)
                
                formatted_decision = {
                    "timestamp": ts_millis,
                    "decision": decision[1],
                    "percentage": decision[2],
                    "reason": decision[3],
                    "notional_value": decision[4],
                    "usdt_balance": decision[5],
                    "btc_entryprice": decision[6]
                }
                formatted_decisions.append(str(formatted_decision))
            return "\n".join(formatted_decisions)
        else:
            return "No decisions found."

def get_current_status():
    #orderbook = binance.futures_order_book(symbol="BTCUSDT")
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

    current_status = {'current_time': current_time, 'notional_value': notional_value, 'usdt_balance': usdt_balance, 'btc_entryprice': btc_entryprice}
    return json.dumps(current_status)


def fetch_and_prepare_data():
    # Fetch data
    #daily = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '1d', start_str = str(month_date))
    #f_hourly = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '4h', start_str = str(month_date))
    hourly = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '1h', start_str = str(week_date))
    minutes = binance.futures_historical_klines(symbol = 'BTCUSDT', interval = '15m', start_str = str(day_date))

    def filter_indices(data):
        indices_to_keep = [0, 1, 2, 3, 4, 5, 7]
        indices_to_keep = set(indices_to_keep)

        filtered_data = []
        for sublist in data:
            filtered_sublist = [item for idx, item in enumerate(sublist) if idx in indices_to_keep]
            filtered_data.append(filtered_sublist)
    
        return filtered_data

    #daily = filter_indices(daily)
    #f_hourly = filter_indices(f_hourly)
    hourly = filter_indices(hourly)
    minutes = filter_indices(minutes)

    #df_daily = pd.DataFrame(daily, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    #df_f_hourly = pd.DataFrame(f_hourly, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    df_hourly = pd.DataFrame(hourly, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])
    df_minutes = pd.DataFrame(minutes, columns=['Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Quote asset volume'])

    def convert_dataframe_values_to_numeric(df):
      for column in df.columns:
          df[column] = pd.to_numeric(df[column], errors='coerce')
      return df

    #df_daily = convert_dataframe_values_to_numeric(df_daily)
    #df_f_hourly= convert_dataframe_values_to_numeric(df_f_hourly)
    df_hourly = convert_dataframe_values_to_numeric(df_hourly)
    df_minutes = convert_dataframe_values_to_numeric(df_minutes)
    
    # Define a helper function to add indicators
    def add_indicators(df):
        # RSI
        df['RSI_14'] = ta.rsi(df['Close'], length=14)

        return df

    # Add indicators to both dataframes
    #df_daily = add_indicators(df_daily)
    #df_f_hourly = add_indicators(df_f_hourly)
    df_hourly = add_indicators(df_hourly)
    df_minutes = add_indicators(df_minutes)

    combined_df = pd.concat([df_hourly, df_minutes], keys=['hourly', 'minutes'])
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

def analyze_data_with_gpt4(data_json, last_decisions, current_status):
    instructions_path = "instructions_v3.md"
    try:
        instructions = get_instructions(instructions_path)
        if not instructions:
            print("No instructions found.")
            return None
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": data_json},
                {"role": "user", "content": last_decisions},
                {"role": "user", "content": current_status}
            ],
            response_format={"type":"json_object"}
        )
        advice = response.choices[0].message.content
        return advice
    except Exception as e:
        print(f"Error in analyzing data with GPT-4: {e}")
        return None

def execute_buy(percentage):
    print("Attempting to buy BTCUSDT with a percentage of USDT balance...")
    try:
        amount_to_invest = round(0.02 * percentage / 100, 3)
        if float(usdt_balance) > 20:
            result = binance.futures_create_order(symbol = "BTCUSDT", type= "MARKET", side = 'BUY', quantity = amount_to_invest)
            print("Buy order successful:", result)
    except Exception as e:
        print(f"Failed to execute buy order: {e}")

def execute_sell(percentage):
    print("Attempting to sell a percentage of BTC...")
    try:
        amount_to_sell = round(0.02 * percentage / 100, 3)
        if float(usdt_balance) > 20:
            result = binance.futures_create_order(symbol = "BTCUSDT", type= "MARKET", side = 'SELL', quantity = amount_to_sell)
            print("Sell order successful:", result)
    except Exception as e:
        print(f"Failed to execute sell order: {e}")

def make_decision_and_execute():
    print("Making decision and executing...")
    try:
        data_json = fetch_and_prepare_data()
        last_decisions = fetch_last_decisions()
        current_status = get_current_status()
    except Exception as e:
        print(f"Error: {e}")
    else:
        max_retries = 5
        retry_delay_seconds = 5
        decision = None
        for attempt in range(max_retries):
            try:
                advice = analyze_data_with_gpt4(data_json, last_decisions, current_status)
                decision = json.loads(advice)
                break
            except Exception as e:
                print(f"JSON parsing failed: {e}. Retrying in {retry_delay_seconds} seconds...")
                time.sleep(retry_delay_seconds)
                print(f"Attempt {attempt + 2} of {max_retries}")
        if not decision:
            print("Failed to make a decision after maximum retries.")
            return
        else:
            try:
                percentage = decision.get('percentage', 100)

                if decision.get('decision') == "buy":
                    execute_buy(percentage)
                elif decision.get('decision') == "sell":
                    execute_sell(percentage)
                
                save_decision_to_db(decision, current_status)
            except Exception as e:
                print(f"Failed to execute the decision or save to DB: {e}")

if __name__ == "__main__":
    initialize_db()
    make_decision_and_execute()
    schedule.every().hour.at(":01").do(make_decision_and_execute)

    while True:
        schedule.run_pending()
        time.sleep(1)