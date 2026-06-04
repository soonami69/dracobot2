import argparse
import csv
import random
from dracobot2.config import SessionLocal
from dracobot2.models import User, UserDetails

session = SessionLocal()

randomize = False
filename = "import.csv"

parser = argparse.ArgumentParser()

parser.add_argument(
    "--randomize",
    action="store_true",
    help="Randomize angel/mortal assignments"
)

parser.add_argument("--seed", type=int)

parser.add_argument(
    "filename",
    nargs="?",
    default="import.csv",
    help="CSV file to import from"
)

args = parser.parse_args()

print("Importing from", args.filename, "with random seed", args.seed, "with randomize=", args.randomize)

randomize = args.randomize

if args.seed is not None:
    random.seed(args.seed)

filename = args.filename

with open(filename, "r", newline='') as f:
    f_reader = csv.reader(f)

    header = next(f_reader)

    # helper function to prevent casting problems if field is empty
    def safe_int(value, default=0):
        try:
            return int(value)
        except Exception:
            return default
        

    def get_row_info(cur_row):
        index = int(cur_row[0])
        name = cur_row[1]
        handle = cur_row[2]
        likes = cur_row[3]
        dislikes = cur_row[4]
        room_number = cur_row[5]
        requests = cur_row[6]
        level = safe_int(cur_row[7])
        dragon_no = safe_int(cur_row[8]) if randomize else int(cur_row[8])
        is_admin = safe_int(cur_row[9])
        return {
            'index': index,
            'name': name,
            'handle': handle,
            'likes': likes,
            'dislikes': dislikes,
            'room_number': room_number,
            'requests': requests,
            'level': level,
            'dragon_no': dragon_no,
            'is_admin': True if is_admin else False
        }


    users_list = {}
    for row in f_reader:
        # guard for newline at end of csv
        if not row:
            continue
        user_obj = get_row_info(row)
        user_db = User(id=user_obj['index'], tele_handle=user_obj['handle'],is_admin=user_obj["is_admin"])
        user_details_db = UserDetails(user=user_db,
                                    name=user_obj['name'],
                                    likes=user_obj['likes'],
                                    dislikes=user_obj['dislikes'],
                                    room_number=user_obj['room_number'],
                                    requests=user_obj['requests'],
                                    level=user_obj['level'])
        users_list[user_obj['index']] = (user_db, user_obj['dragon_no'])
        session.add(user_details_db)

    session.commit()

    if randomize:

        users = [user_data[0] for user_data in users_list.values()]

        shuffled_users = users[:]
        random.shuffle(shuffled_users)

        for i, user in enumerate(shuffled_users):
            assigned_user = shuffled_users[(i + 1) % len(shuffled_users)]
            user.dragon = assigned_user
            user.dragon_id = assigned_user.id
    
    else:
        for user_id in users_list:
            user_db, dragon_id = users_list[user_id]
            user_db.dragon = users_list[dragon_id][0]

    session.commit()