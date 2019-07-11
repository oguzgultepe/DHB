from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, Filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import telegramcalendar
from timezonefinder import TimezoneFinder
import schedule
from threading import Thread
from datetime import datetime, timedelta
import pytz
import sqlite3
from sqlite3 import Error
import re
import os
import time
import warnings
import pickle
import numpy as np
import pandas as pd
from sklearn import preprocessing
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.tree import DecisionTreeRegressor
from sklearn.svm import SVR
from sklearn.model_selection import train_test_split, GridSearchCV
from sklearn.ensemble import BaggingRegressor, RandomForestRegressor
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

primary_key = '640443271:AAEXY8w0JaSVcXT_3TrzBPK1GGtCweOQPD8'
testing_key = '826578423:AAHYAQ-HDFpjP29pdcbdhZffqU9WgLZvghU'

database_dir = 'db'
database = os.path.join(database_dir,'dhb.db')
goals = ['Lose Weight',
         'Maintain Weight',
         'Gain Weight']


type_pattern = r'''\b
(?:
    (?P<meal>meal|breakfast|lunch|dinner)|
    (?P<snack>snack|small|little|few)
)
\b'''

log_pattern = r'''\b
(eat|ate|eaten|food)
\b'''

absolute_time_pattern = r'''\b
(?:at\s*)?
(?:
    (?P<hours>
        [01]?\d|2[0-3]) #Hours part
    (?:[:\.\s]
    (?P<minutes>
        [0-5]?\d))? #Optional minutes part
    (?P<AmPm>\s*[ap]m)? #Optional 12 hour format
|(?P<hours_alt>[01]\d|2[0-3])(?P<minutes_alt>[0-5]\d)) #Alternative format
\b'''

relative_time_pattern = r'''\b
(?P<hours>
    (?:half(?:\s*\b(?:a|an|)\b\s*)?| #Capture 'half'
    \ba\b|\ban\b| #Capture a or an
    1?[0-9]|2[0-4])? #Capture numericals
\s*
(?:h|hour)s?)?
\s*
(?P<minutes>
    (?:\ba\b|\ban\b| #Capture a or an
    [0-9]{1,2}) #Capture numericals
\s*
(?:m|min|minute)s?\b)?
\s*
(?:ago|before|prior)
\b'''

absolute_time_regex = re.compile(absolute_time_pattern, flags=re.X)
relative_time_regex = re.compile(relative_time_pattern, flags=re.X)
type_regex = re.compile(type_pattern, flags=re.X)
log_regex = re.compile(log_pattern, flags=re.X)

#Database functions

def get_database_connection(database):
    conn = None
    while(conn is None):
        try:
            conn = sqlite3.connect(database)
        except Error as e:
            pass
    return conn

def return_database_connection(conn):
    conn.close()

def setup():
    if not os.path.exists(database_dir):
        os.mkdir(database_dir)
        print("Database directory ", database_dir, "created.")
    #Create the user-goal table
    #Columns: 
    #userID:= Telegram userID
    #goal:= Dietary goal of the user
    #timeZone:= Time Zone of the user 
    create_users_table = '''CREATE TABLE users
                            (userID INT PRIMARY KEY,
                            goal INT NOT NULL,
                            timeZone TEXT NOT NULL)'''
    #Create the user-meal table
    #Columns: 
    #user:= User id of the user associated with the meal
    #mealDate:= Date of the meal, stored as '%Y-%m-%d'
    #mealTime:= Time of the meal, stored as '%H-%M'
    #mealType:= Type of meal, 0 for snack, 1 for full meal
    create_meals_table = '''CREATE TABLE meals
                            (user INT,
                            mealDate TEXT,
                            mealTime TEXT,
                            mealType INT,
                            FOREIGN KEY(user) REFERENCES users(userID))'''
    #Create the model table
    #Columns:
    #user:= User id of the user associated with the model
    #model:= Best performing model for the user, pickled 
    #feedback:= User feedback on notification timing, denotes minutes
    create_models_table= '''CREATE TABLE models
                            (user INT,
                            model BlOB,
                            feedback INT,
                            FOREIGN KEY(user) REFERENCES users(userID))'''
    conn = get_database_connection(database)
    c = conn.cursor()
    c.execute(create_users_table)
    c.execute(create_meals_table)
    c.execute(create_models_table)
    conn.commit()
    return_database_connection(conn)
    print('Setup successfully completed.')

def start(bot, update):
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users WHERE userId=?", (user_id,))
    except Error as e:
        print(e)
        error_text = "There was an error. Please try again later."
        bot.send_message(chat_id=chat_id, text= error_text)
    registered = not (c.fetchone() is None)
    if registered:
        return_database_connection(conn)
        help_text = "You are already registered in the system.\n"
        help_text += "If you want to change your timezone, you can use the /change_timezone command.\n"
        help_text += "If you want to change your goal, you can use the /change_goal command.\n"
        bot.send_message(chat_id=chat_id, text=help_text)
        return -1
    else:
        c.execute("INSERT INTO users (userID, goal, timeZone) VALUES (?, 0, 0)",
                  (user_id,))
        conn.commit()
        return_database_connection(conn)
    start_text = "Hello! I am your virtual dietary helper. "
    start_text += "I am here to motivate you towards your dietary goals.\n\n"
    start_text += "In order to do this, I need to know some things about you.\n\n"
    start_text += "First: your timezone.\n"
    bot.send_message(chat_id=chat_id, text=start_text)
    return change_timezone(bot, update)

def start_assert(bot, update):
    chat_id = update.message.chat_id
    assert_text = "This information is needed for registration.\n"
    bot.send_message(chat_id=chat_id, text=assert_text)

def timezone_received(bot, update):
    set_timezone(bot, update)
    chat_id = update.message.chat_id
    goal_text= "Next, you need to select a goal:\n"
    bot.send_message(chat_id=chat_id, text=goal_text)
    change_goal(bot,update)
    return 1

def goal_selected(bot, update):
    set_goal(bot, update)
    chat_id = update.callback_query.message.chat_id
    information_text = "When I know enough about your eating habits I will start motivating you towards your goal.\n"
    information_text += "For now, please just let me know when you have a meal or a snack.\n"
    bot.send_message(chat_id=chat_id, text=information_text)
    return -1

def cancel_operation(bot, update, user_data):
    chat_id = update.message.chat_id
    try:
        markup_id = user_data['markup_id']
        bot.deleteMessage(chat_id=chat_id, message_id=markup_id)
    except KeyError:
        pass
    cancel_text = "Operation cancelled.\n"
    bot.send_message(chat_id=chat_id, text=cancel_text)
    return -1

#Timezone functions 
def change_timezone(bot, update):
    chat_id = update.message.chat_id
    timezone_text = "Please share your location with me so I can find your timezone.\n"
    timezone_text += "Your location will only be used to find your timezone and will not be stored on our servers.\n"
    bot.send_message(chat_id=chat_id, text=timezone_text)
    return 0

def set_timezone(bot, update):
    location = update.message.location
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    longitude = location.longitude
    latitude = location.latitude
    timezoneFinder = TimezoneFinder()
    timezone = timezoneFinder.timezone_at(lng=longitude, lat=latitude)
    confirmation_text = "Your timezone is saved as {0}.\n".format(timezone.replace('_',' '))
    confirmation_text += "You can change your timezone at anytime with the command /change_timezone .\n"
    bot.send_message(chat_id=chat_id, text=confirmation_text)
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET timeZone=? WHERE userID=?", (timezone, user_id))
    except Error as e:
        print(e)
        error_text = "There was an error and your timezone settings could not be saved.\n"
        bot.send_message(chat_id=chat_id, text= error_text)
    conn.commit()
    return_database_connection(conn)
    return -1

#Goal functions
def change_goal(bot, update, user_data):
    chat_id = update.message.chat_id
    goal_text = "Please select your goal:\n"
    choices = [[InlineKeyboardButton(g, callback_data=i) for i, g in enumerate(goals)]]
    reply_markup = InlineKeyboardMarkup(choices)
    sent_markup = bot.send_message(chat_id=chat_id, text=goal_text, reply_markup=reply_markup)
    user_data['markup_id'] = sent_markup.message_id
    return 0

def set_goal(bot, update):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    goal = int(query.data)
    query.answer()
    query.message.delete()
    confirmation_text = "You have selected {0} as your goal.\n".format(goals[goal].lower())
    confirmation_text += "You can change your goal at anytime with the command /change_goal.\n"
    bot.send_message(chat_id=chat_id, text=confirmation_text)
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET goal=? WHERE userID=?", (goal, user_id))
    except Error as e:
        print(e)
        error_text = "There was an error and your goal settings could not be saved.\n"
        bot.send_message(chat_id=chat_id, text= error_text)
    conn.commit()
    return_database_connection(conn)
    return -1

#Meal logging functions

def save_meal(user_id, meal_type, meal_time):
    meal_date = meal_time.strftime('%Y-%m-%d')
    meal_time = meal_time.strftime('%H:%M')
    saved = False
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO meals (user, mealDate, mealTime, mealType) VALUES (?,?,?,?)",
                  (user_id, meal_date, meal_time, meal_type))
        saved = True
    except Error as e:
        print(e)

    conn.commit()
    return_database_connection(conn)
    return saved

def extract_time(user_id, text):
    time = None
    timezone = get_timezone(user_id)
    text = text.lower()

    match = relative_time_regex.search(text)
    if not match is None:
        hours = 0
        minutes = 0
        if not match['hours'] is None:
            if 'half' in match['hours']:
                minutes = 30
            elif not re.search(r'\d+', match['hours']) is None:
                hours = int(re.search(r'\d+', match['hours']).group(0))
            else:
                hours = 1

        if not match['minutes'] is None:
            if not re.search(r'\d+', match['minutes']) is None:
                minutes = int(re.search(r'\d+', match['minutes']).group(0))
            else:
                minutes = 1

        time = datetime.now(timezone)
        time = time - timedelta(hours=hours, minutes=minutes)
        return time

    match = absolute_time_regex.search(text)
    if not match is None:
        if not match['hours'] is None:
            hour = int(match['hours'])
            if match['minutes']:
                minute = int(match['minutes'])
            else:
                minute = 0
            if match['AmPm']:
                pm = match['AmPm'].lower().strip() == 'pm'
                hour += 12 * int(pm)
        else:
            hour = int(match['hours_alt'])
            minute = int(match['minutes_alt'])
        time = datetime.now(timezone)
        time = time.replace(hour=hour, minute=minute)
        if 'yesterday' in text:
            time = time - timedelta(days=1)
        return time

    if 'now' in text or 'just' in text:
        time = datetime.now(timezone)

    return time

def get_timezone(user_id):
    timezone = None
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("SELECT timeZone FROM users WHERE userId=?", (user_id,))
        timezone = pytz.timezone(c.fetchone()[0])
    except Error as e:
        print(e)

    return timezone

def extract_type(text):
    text = text.lower()
    match = type_regex.search(text)
    if match is None:
        return None
    elif not match['meal'] is None:
        return 1
    elif not match['snack'] is None:
        return 0
    else:
        return None

def confirmation_message(meal_type, meal_time):
    confirmation_text = 'Your {} {} at {} is successfully saved!\n'.format(meal_time.strftime("%b %d"), {0:'snack',1:'meal'}[meal_type], meal_time.strftime("%H:%M"))
    confirmation_text += 'If there is a problem with this entry, you can remove it using the /remove_entry command.\n'
    return confirmation_text

def process(bot, update, user_data):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    meal_time = extract_time(user_id, text)
    meal_type = extract_type(text)
    log_bool = not log_regex.search(text.lower()) is None
    schedule = False

    if not (meal_type is None or meal_time is None):
        if save_meal(user_id, meal_type, meal_time):
            message = confirmation_message(meal_type, meal_time)
            schedule = True
        else:
            message = "There was an error and the meal could not be saved.\n"
        state = -1
    elif not meal_time is None:
        user_data['meal_time'] = meal_time
        message = "Was this a meal or a snack?\n"
        state = 1
    elif not meal_type is None:
        user_data['meal_type'] = meal_type
        message = "When was this {0}?\n".format({0:'snack',1:'meal'}[meal_type])
        state = 2
    elif log_bool:
        message = "Was this a meal or a snack?\n"
        state = 0
    else:
        message = "I don't understand. Can you explain in other words?\n"
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    if schedule:
        schedule_message(bot, user_id)
    return state

def get_type(bot, update, user_data):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    error_message = "There was an error and the meal could not be saved.\n"
    meal_time = None
    schedule = False

    try:
        meal_time = user_data['meal_time']
    except KeyError:
        pass

    meal_type = extract_type(text)

    if meal_time is None:
        message = error_message
        state = -1
    elif meal_type is None:
        message = "I still don't understand.\n"
        message += "Was this a meal or a snack?\n"
        state = 1
    elif save_meal(user_id, meal_type, meal_time):
        message = confirmation_message(meal_type, meal_time)
        state = -1
        schedule = True
    else:
        message = error_message
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    if schedule:
        schedule_message(bot, user_id)
    return state

def get_time(bot, update, user_data):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    error_message = "There was an error and the meal could not be saved.\n"
    meal_type = None
    schedule = False

    try:
        meal_type = user_data['meal_type']
    except KeyError:
        pass

    meal_time = extract_time(user_id, text)

    if meal_type is None:
        message = error_message
        state = -1
    elif meal_time is None:
        message = "I still don't understand.\n"
        message += "When did you eat?\n"
        state = 2
    elif save_meal(user_id, meal_type, meal_time):
        message = confirmation_message(meal_type, meal_time)
        state = -1
        schedule = True
    else:
        message = error_message
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    if schedule:
        schedule_message(bot, user_id)
    return state

def remove_entry(bot, update, user_data):
    chat_id = update.message.chat_id
    text = "Please select the date of the entry.\n"
    markup = telegramcalendar.create_calendar()
    sent_markup = bot.send_message(chat_id=chat_id, text=text, reply_markup=markup)
    user_data['markup_id'] = sent_markup.message_id
    return 0



def calendar_action(bot, update, user_data):
    selected,date = telegramcalendar.process_calendar_selection(bot, update)
    if selected:
        chat_id = update.callback_query.message.chat_id
        user_id = update.callback_query.from_user.id
        entries = None
        conn = get_database_connection(database)
        c = conn.cursor()
        try:
            c.execute("SELECT mealTime FROM meals WHERE user=? and mealDate=?",(user_id, date.strftime('%Y-%m-%d')))
            entries = c.fetchall()
        except Error as e:
            print(e)

        return_database_connection(conn)

        if entries is None:
            text = "There was an error and the operation had to be cancelled.\n"
            state = -1
        elif not entries:
            text = 'No entries found for the selected date.\n'
            reply_markup = None
            state = -1
        else:
            user_data['date'] = date
            text = 'Please select the entry you wish to remove.\n'
            state =1
            entries = list(map(lambda x:x[0], entries))
            choices = [[InlineKeyboardButton(entry, callback_data=entry) for entry in entries]]
            reply_markup = InlineKeyboardMarkup(choices)
            #send an inline keyboard with the times of the entries
        sent_markup = bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup)
        user_data['markup_id'] = sent_markup.message_id
        return state

def entry_selected(bot, update, user_data):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    meal_time = query.data
    meal_date = user_data['date']
    query.answer()
    query.message.delete()
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute('DELETE FROM meals WHERE user=? and mealDate=? and mealTime=?',
                 (user_id, meal_date.strftime('%Y-%m-%d'), meal_time))
        conn.commit()
        text = 'Entry on {} at {} successfully removed.\n'.format(meal_date.strftime("%b %d"),meal_time)
    except Error as e:
        print(e)
        text = "There was an error and the operation had to be cancelled.\n"

    return_database_connection(conn)
    bot.send_message(chat_id=chat_id, text=text)
    return -1

#Predict the next entry for a user and schedule a message
def schedule_message(bot, user_id):
    schedule.clear(str(user_id))
    next_entry = predict(user_id, 10)
    if not next_entry is None:
        schedule.every().day.at(next_entry.strftime('%H:%M')).do(send_intervention_message, bot, user_id).tag(str(user_id))

#Send intervention message and feedback menu, meant to be scheduled
def send_intervention_message(bot, user_id):
    text = 'It looks like you might be getting hungry.\n'
    text += 'Please rate the timing of this message.\n'
    choices = [[InlineKeyboardButton('Too Early', callback_data=30),
                InlineKeyboardButton('Early', callback_data=15),
                InlineKeyboardButton('On Time', callback_data=0),
                InlineKeyboardButton('Late', callback_data=-15),
                InlineKeyboardButton('Too Late', callback_data=-30)]]

    reply_markup = InlineKeyboardMarkup(choices)
    bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)
    return schedule.CancelJob

def process_feedback(bot, update):
    query = update.callback_query
    chat_id = query.message.chat_id
    user_id = query.from_user.id
    feedback = int(query.data)
    query.answer()
    query.message.delete()
    conn = get_database_connection(database)
    c = conn.cursor()
    c.execute('SELECT feedback FROM models  WHERE user=?',(user_id,))
    feedback_old = c.fetchone()
    feedback += feedback_old[0]
    c.execute('UPDATE models SET feedback=? WHERE user=?',(feedback, user_id))
    conn.commit()
    return_database_connection(conn)



####Machine Learning Starts here
#Accepts a numpy array of logs
#Returns array of feautures and targets
def feature_template(data):
    new_data = np.zeros((data.shape[0]-1,12))
    current_datetime = ''
    meal_count = 0
    snack_count = 0
    counter = 0
    meal = 0
    first = True
    for row in data:
        if first:
            current_datetime = datetime.strptime(row[1]+' '+row[2], '%Y-%m-%d %H:%M')
            meal = row[3]
            first = False
            continue

        new_datetime = datetime.strptime(row[1]+' '+row[2], '%Y-%m-%d %H:%M')
        new_data[counter][int(current_datetime.strftime('%w'))] = 1
        new_data[counter][7] = meal_count
        new_data[counter][8] = snack_count
        new_data[counter][9] = meal
        new_data[counter][10] = int(current_datetime.strftime('%H')) * 60 + int(current_datetime.strftime('%M'))
        diff = new_datetime - current_datetime
        new_data[counter][11] = diff.days*1440 + diff.seconds/60
        if current_datetime.date() == new_datetime.date():
            if meal:
                meal_count += 1
            else:
                snack_count += 1
        else:
            meal_count = 0
            snack_count = 0

        current_datetime = new_datetime
        meal = row[3]
        counter += 1

    last_entry = np.zeros((11,1))
    last_entry[int(current_datetime.strftime('%w'))] = 1
    last_entry[7] = meal_count
    last_entry[8] = snack_count
    last_entry[9] = meal
    last_entry[10] = int(current_datetime.strftime('%H')) * 60 + int(current_datetime.strftime('%M'))

    previous_entries = pd.DataFrame(new_data, columns=
                                    ['Sunday','Monday','Tuesday','Wednesday',
                                    'Thursday','Friday','Saturday','Meals So Far',
                                    'Snacks So Far','Meal or Snack','Time of Entry','Next Entry'])

    return previous_entries, last_entry

#Data preprocessing
def preprocess(df):
    X = df.values[:,:11]
    y = df.values[:,11]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.1, random_state=42)
    X_min_max_scaler = preprocessing.MinMaxScaler()
    y_min_max_scaler = preprocessing.MinMaxScaler()
    X_train = X_min_max_scaler.fit_transform(X_train)
    y_train = np.ravel(y_min_max_scaler.fit_transform(y_train.reshape(-1, 1)))
    X_test = X_min_max_scaler.transform(X_test)
    y_test = np.ravel(y_min_max_scaler.transform(y_test.reshape(-1, 1)))
    return {'X_train':X_train,
            'X_test':X_test,
            'y_train':y_train,
            'y_test':y_test,
            'X_scaler':X_min_max_scaler,
            'y_scaler':y_min_max_scaler}

def train_test(data, model, parameters=None, ensemble=False, rfr=False):
    if ensemble:
        clf = BaggingRegressor(model,max_samples=1.0, max_features=0.7)
    elif rfr:
        clf = clf = RandomForestRegressor(max_features=0.7)
    else:
        clf = GridSearchCV(model, parameters, cv=10)
    clf.fit(data['X_train'], data['y_train'])
    score = clf.score(data['X_test'], data['y_test'])
    return {'model':clf,'score':score}

def models(data_dict):
    clf_dict = {}
    clf_dict['tree_model'] = train_test(data_dict, DecisionTreeRegressor(),{})
    clf_dict['linear_model'] = train_test(data_dict, LinearRegression(), {})
    clf_dict['ridge_model'] = train_test(data_dict, Ridge(), {'alpha':[1.0,0.5]})
    clf_dict['svr_model'] = train_test(data_dict, SVR(kernel='linear'), {'C':[1.0,0.5,0.1]})
    clf_dict['random_forest_model'] = train_test(data_dict, RandomForestRegressor(max_features=0.7), rfr=True)
    clf_dict['linear_ensemble_model'] = train_test(data_dict, LinearRegression(), ensemble=True)
    clf_dict['ridge_ensemble_model'] = train_test(data_dict, Ridge(), ensemble=True)
    clf_dict['svr_ensemble_model'] = train_test(data_dict, SVR(kernel='linear'), ensemble=True)
    return clf_dict

#Import the data from the database
def get_data(user_id):
    conn = get_database_connection(database)
    c = conn.cursor()
    c.execute('SELECT * FROM meals WHERE user=?',(user_id,))
    meals = c.fetchall()
    c.execute('SELECT * FROM models WHERE user=?',(user_id,))
    data = c.fetchone()
    if data is None:
        model = None
        feedback = 0
        score = 0
    else:
        model_data = pickle.loads(data[1])
        feedback = data[2]
        model = model_data['model']
        score = model_data['score']
    return_database_connection(conn)
    return meals, model, score, feedback

#Normalize the data
def normalize(data):
    data.mealTime = data.mealTime.apply(lambda x:x[:5])
    data = data.sort_values(by=['mealDate','mealTime'])
    return data

def save_model(user_id, model, feedback):
    model_data = pickle.dumps(model)
    conn = get_database_connection(database)
    c = conn.cursor()
    c.execute('REPLACE INTO models(user,model,feedback) VALUES(?,?,?)',(user_id, model_data, feedback))
    conn.commit()
    return_database_connection(conn)

#Returns the prediction for the next entry time
def predict(user_id, iterations = None):
    meals, best_model, best_score, feedback = get_data(user_id)
    data = pd.DataFrame(meals, columns =['userId', 'mealDate', 'mealTime', 'mealType'])
    data = normalize(data)
    previous_entries, x_predict = feature_template(data.values)
    data_dict = preprocess(previous_entries)
    x_predict = data_dict['X_scaler'].transform(x_predict.T)
    if best_score == 0:
        #First time training a model for user, 100 iterations
        iterations = 100
    elif not iterations:
        iterations = 1
    for i in range(iterations):
        clf_dict = models(data_dict)
        for name, clf in clf_dict.items():
            if clf['score'] > best_score:
                best_model = clf['model']
                best_score = clf['score']

    if best_model is None:
        return None
    else:
        save_model(user_id, {'model':best_model, 'score':best_score}, feedback)

    prediction = best_model.predict(x_predict)
    last_entry = datetime.strptime(data['mealDate'].iat[-1]+' '+data['mealTime'].iat[-1], '%Y-%m-%d %H:%M')
    minutes = data_dict['y_scaler'].inverse_transform(prediction.reshape(1,-1))
    delta = timedelta(minutes=(minutes[0][0]+feedback))
    next_entry = last_entry + delta
    return next_entry

def create_models_table():
    conn = get_database_connection(database)
    c = conn.cursor()
    create_phrase = '''CREATE TABLE models
                    (user INT UNIQUE,
                    model BlOB,
                    feedback INT,
                    FOREIGN KEY(user) REFERENCES users(userID))'''
    c.execute(create_phrase)
    conn.commit()
    return_database_connection(conn)

def check_schedule():
    while True:
        schedule.run_pending()
        time.sleep(1)

def main():
    schedule_thread = Thread(target=check_schedule)
    schedule_thread.start()

    database_exists = os.path.isfile(database)
    if not database_exists:
        setup()
    updater = Updater(testing_key)
    dispatcher = updater.dispatcher

    #Base handlers for start
    start_handler = CommandHandler('start',start)
    start_assert_handler = MessageHandler(Filters.all, start_assert)
    timezone_received_handler = MessageHandler(Filters.location, timezone_received)
    goal_selected_handler = CallbackQueryHandler(goal_selected)
    #Base handlers for timezone functionality
    change_timezone_handler = CommandHandler('change_timezone', change_timezone)
    set_timezone_handler = MessageHandler(Filters.location, set_timezone)
    #Base handlers for goal functionality
    change_goal_handler = CommandHandler('change_goal', change_goal, pass_user_data=True)
    set_goal_handler = CallbackQueryHandler(set_goal)
    #Base handlers for meal logging
    initial_handler= MessageHandler(Filters.text, process, pass_user_data=True)
    get_type_handler = MessageHandler(Filters.text, get_type, pass_user_data=True)
    get_time_handler = MessageHandler(Filters.text, get_time, pass_user_data=True)
    #Base handlers for remove entry
    remove_entry_handler = CommandHandler('remove_entry', remove_entry, pass_user_data=True)
    calendar_action_handler = CallbackQueryHandler(calendar_action, pass_user_data=True)
    entry_selected_handler = CallbackQueryHandler(entry_selected, pass_user_data=True)
    #Auxiliary cancel handler
    cancel_operation_handler = MessageHandler(Filters.all, cancel_operation, pass_user_data=True)
    #Feedback handler
    feedback_handler = CallbackQueryHandler(process_feedback)

    #Conversation handler for start command
    dispatcher.add_handler(ConversationHandler([start_handler], {0:[timezone_received_handler], 1:[goal_selected_handler]}, [start_assert_handler]))
    #Conversation handler for change_timezone command
    dispatcher.add_handler(ConversationHandler([change_timezone_handler],{0:[set_timezone_handler]}, [cancel_operation_handler]))
    #Conversation handler for change_goal command
    dispatcher.add_handler(ConversationHandler([change_goal_handler], {0:[set_goal_handler]}, [cancel_operation_handler]))
    #Conversation handler for remove entry
    dispatcher.add_handler(ConversationHandler([remove_entry_handler],{0:[calendar_action_handler], 1:[entry_selected_handler]}, [cancel_operation_handler]))
    #Conversation handler for meal logging
    dispatcher.add_handler(ConversationHandler([initial_handler],{0:[initial_handler], 1:[get_type_handler], 2:[get_time_handler]}, [cancel_operation_handler]))
    #Feedback handler
    dispatcher.add_handler(feedback_handler)

    updater.start_polling()
    updater.idle()
    schedule_thread.join()

if __name__ == '__main__':
    main()
