import csv
import random
from dracobot2.config import SessionLocal
from dracobot2.models import User, UserDetails

session = SessionLocal()

def get_row_info(cur_row):
    index = int(cur_row[0])
    name = cur_row[1]
    handle = cur_row[2]
    likes = cur_row[3]
    dislikes = cur_row[4]
    room_number = cur_row[5]
    requests = cur_row[6]
    level = int(cur_row[7])
    # Ignore dragon_no from CSV, will assign later
    return {
        'index': index,
        'name': name,
        'handle': handle,
        'likes': likes,
        'dislikes': dislikes,
        'room_number': room_number,
        'requests': requests,
        'level': level,
    }

def generate_single_cycle(user_ids):
    remaining = user_ids[:]
    cycle_map = {}

    start = remaining.pop(0)
    current = start

    while remaining:
        next_user = random.choice(remaining)
        remaining.remove(next_user)
        cycle_map[current] = next_user
        current = next_user

    cycle_map[current] = start

    return [cycle_map[user] for user in user_ids]

with open("import.csv", "r", newline='') as f:
    f_reader = csv.reader(f)
    header = next(f_reader)

    users_data = [get_row_info(row) for row in f_reader]

user_ids = [user['index'] for user in users_data]

# Generate the single-cycle dragon assignment
dragon_ids = generate_single_cycle(user_ids)

users_list = {}

# Create User and UserDetails, assign dragon_no from cycle
for user_obj, dragon_id in zip(users_data, dragon_ids):
    user_db = User(id=user_obj['index'], tele_handle=user_obj['handle'])
    user_details_db = UserDetails(
        user=user_db,
        name=user_obj['name'],
        likes=user_obj['likes'],
        dislikes=user_obj['dislikes'],
        room_number=user_obj['room_number'],
        requests=user_obj['requests'],
        level=user_obj['level']
    )
    users_list[user_obj['index']] = (user_db, dragon_id)
    session.add(user_details_db)

session.commit()

# Now link each user to their dragon
for user_id, (user_db, dragon_id) in users_list.items():
    user_db.dragon = users_list[dragon_id][0]

for user_id, (user_db, dragon_id) in users_list.items():
    print(f"User {user_id} → Dragon {dragon_id}")

session.commit()
