from telegram.ext import Updater, CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, Filters
from telegram import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from nltk.tokenize import word_tokenize
from timezonefinder import TimezoneFinder
from datetime import datetime, timedelta
import pytz
import sqlite3
from sqlite3 import Error
import re
import os

#TODO implement absolute and relative time
#Global variables

database_dir = 'db'
database = os.path.join(database_dir,'dhb.db')
goals = ['Lose Weight',
         'Maintain Weight',
         'Gain Weight']

meal_triggers = {'meal', 'breakfast', 'lunch', 'dinner'}
snack_triggers = {'snack', 'small', 'little'}
log_triggers = {'eat','ate','eaten','food'}


absolute_time_pattern = r'''\b
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
    #mealType:= Type of meal, 0 for snack, 1 for full meal
    #mealTime:= Time of the meal as ISO8601 strings
    #user:= Chat id of the user associated with the meal
    create_meals_table = '''CREATE TABLE meals
                            (mealType INT,
                            mealTime TEXT,
                            user INT,
                            FOREIGN KEY(user) REFERENCES users(userID))'''
    conn = get_database_connection(database)
    c = conn.cursor()
    c.execute(create_users_table)
    c.execute(create_meals_table)
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

#Timezone functions 

def timezone_assert(bot, update):
    chat_id = update.message.chat_id
    assert_text = "I need your location to find your timezone.\n"
    bot.send_message(chat_id=chat_id, text=assert_text)
    return 0

def timezone_received(bot, update):
    set_timezone(bot, update)
    chat_id = update.message.chat_id
    goal_text= "Next, you need to select a goal:\n"
    bot.send_message(chat_id=chat_id, text=goal_text)
    change_goal(bot,update)
    return 1

def change_timezone(bot, update):
    chat_id = update.message.chat_id
    timezone_text = "Please share your location with me so I can find your timezone.\n"
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

def goal_assert(bot, update):
    chat_id = update.message.chat_id
    assert_text = "Please select a goal.\n"
    bot.send_message(chat_id=chat_id, text=assert_text)
    return 1

def goal_selected(bot, update):
    set_goal(bot, update)
    chat_id = update.callback_query.message.chat_id
    information_text = "When I know enough about your eating habits I will start motivating you towards your goal.\n"
    information_text += "For now, please just let me know when you have a meal or a snack.\n"
    bot.send_message(chat_id=chat_id, text=information_text)
    return -1

def change_goal(bot, update):
    chat_id = update.message.chat_id
    goal_text = "Please select your goal:\n"
    choices = [[InlineKeyboardButton(g, callback_data=i) for i, g in enumerate(goals)]]
    reply_markup = InlineKeyboardMarkup(choices)
    bot.send_message(chat_id=chat_id, text=goal_text, reply_markup=reply_markup)
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
    if not (meal_time is None):
        meal_time = meal_time.strftime('%Y-%m-%d %H:%M')
    saved = False
    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO meals (mealType, mealTime, user) VALUES (?,?,?)",
                  (meal_type, meal_time, user_id))
        saved = True
    except Error as e:
        print(e)

    conn.commit()
    return_database_connection(conn)
    return saved

def update_meal(user_id, meal_type=None, meal_time=None):
    return_value = None
    if meal_type is None:
        given_value = str(meal_time)
        select = "SELECT mealType FROM meals WHERE user=? and mealTime IS NULL"
        update = "UPDATE meals SET mealTime=? WHERE user=? and mealTime IS NULL"
    elif meal_time is None:
        given_value = meal_type
        select = "SELECT mealTime FROM meals WHERE user=? and mealType IS NULL"
        update = "UPDATE meals SET mealType=? WHERE user=? and mealType IS NULL"
    else:
        print('Error: update_meal function takes exactly one optional argument.')
        return None

    conn = get_database_connection(database)
    c = conn.cursor()
    try:
        c.execute(select, (user_id,))
        return_value = c.fetchone()
        c.execute(update,(given_value, user_id))
    except Error as e:
        print(e)

    conn.commit()
    return_database_connection(conn)
    if isinstance(return_value[0], str):
        return_value = datetime.strptime(return_value[0], '%Y-%m-%d %H:%M')
    else:
        return_value = return_value[0]
    return return_value

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

def extract_type(tokens):
    if bool(meal_triggers & set(tokens)):
        return 1
    elif bool(snack_triggers & set(tokens)):
        return 0
    else:
        return None

def confirmation_message(meal_type, meal_time):
    return 'Your {} {} at {} is successfully saved!\n'.format(meal_time.strftime("%b %d"), {0:'snack',1:'meal'}[meal_type], meal_time.strftime("%H:%M"))

def process(bot, update):
    save = False
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    tokens = word_tokenize(text.lower())
    meal_time = extract_time(user_id, text)
    meal_type = extract_type(tokens)

    if not (meal_type is None or meal_time is None):
        message = confirmation_message(meal_type, meal_time)
        save = True
        state = -1
    elif not meal_time is None:
        save = True
        message = "Was this a meal or a snack?\n"
        state = 1
    elif not meal_type is None:
        save = True
        message = "When was this {0}?\n".format({0:'snack',1:'meal'}[meal_type])
        state = 2
    elif bool(log_triggers & set(tokens)):
        message = "Was this a meal or a snack?\n"
        state = 0
    else:
        message = "I don't understand. Can you explain in other words?\n"
        state = -1

    if save and not save_meal(user_id, meal_type, meal_time):
        message = "There was an error and the meal could not be saved.\n"
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    return state

def get_type(bot, update):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    tokens = word_tokenize(text.lower())
    meal_type = extract_type(tokens)

    if meal_type is None:
        message = "I still don't understand.\n"
        message += "Was this a meal or a snack?\n"
        state = 1
    else:
        meal_time = update_meal(user_id, meal_type=meal_type)
        if not meal_time is None:
            message = confirmation_message(meal_type, meal_time)
        else:
            message = "There was an error and the meal could not be saved.\n"
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    return state

def get_time(bot, update):
    text = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id

    meal_time = extract_time(user_id, text)

    if meal_time is None:
        message = "I still don't understand.\n"
        message += "When did you eat?\n"
        state = 2
    else:
        meal_type = update_meal(user_id, meal_time=meal_time)
        if not meal_type is None:
            message = confirmation_message(meal_type, meal_time)
        else:
            message = "There was an error and the meal could not be saved.\n"
        state = -1

    bot.send_message(chat_id=chat_id, text=message)
    return state



def main():
    database_exists = os.path.isfile(database)
    if not database_exists:
        setup()
    updater = Updater('640443271:AAEXY8w0JaSVcXT_3TrzBPK1GGtCweOQPD8')
    dispatcher = updater.dispatcher

    #Base start command handler
    start_handler = CommandHandler('start',start)
    #Base handlers for timezone functionality
    timezone_received_handler = MessageHandler(Filters.location, timezone_received)
    change_timezone_handler = CommandHandler('change_timezone', change_timezone)
    set_timezone_handler = MessageHandler(Filters.location, set_timezone)
    timezone_assert_handler = MessageHandler(Filters.all, timezone_assert)
    #Base handlers for goal functionality
    goal_selected_handler = CallbackQueryHandler(goal_selected)
    change_goal_handler = CommandHandler('change_goal',change_goal)
    set_goal_handler = CallbackQueryHandler(set_goal)
    goal_assert_handler = MessageHandler(Filters.all, goal_assert)
    #Base handlers for meal logging
    initial_handler= MessageHandler(Filters.text, process)
    get_type_handler = MessageHandler(Filters.text, get_type)
    get_time_handler = MessageHandler(Filters.text, get_time)

    #Conversation handler for start command
    dispatcher.add_handler(ConversationHandler([start_handler], {0:[timezone_received_handler, timezone_assert_handler],
                                                                 1:[goal_selected_handler, goal_assert_handler]}, []))
    #Conversation handler for change_timezone command
    dispatcher.add_handler(ConversationHandler([change_timezone_handler],{0:[set_timezone_handler,timezone_assert_handler]},[]))
    #Conversation handler for change_goal command
    dispatcher.add_handler(ConversationHandler([change_goal_handler], {0:[set_goal_handler, goal_assert_handler]}, []))
    #Conversation handler for meal logging
    dispatcher.add_handler(ConversationHandler([initial_handler],{0:[initial_handler], 1:[get_type_handler], 2:[get_time_handler]}, []))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
