import datetime
from typing import Tuple

import telegram
from sqlalchemy import and_
from telegram.ext import ContextTypes

from dracobot2.models import DailyScheduledMessage, MessageMapping, Role, User
from dracobot2.utils.msg_mappings import forward_message
from dracobot2.utils.resources import format_message
from dracobot2.utils.timezone import TIMEZONE
from main import db_session

active_jobs_by_time = {}


def execute_jobs_at_time_handler(time: Tuple[int, int]):
    @db_session
    async def execute_jobs_handler(context: ContextTypes.DEFAULT_TYPE, session):
        #n Local date
        today_date = datetime.date.today()
        active_messages_to_send_at_time = (
            session.query(DailyScheduledMessage)
            .filter(
                and_(
                    DailyScheduledMessage.active_from <= today_date,
                    DailyScheduledMessage.active_to >= today_date,
                    DailyScheduledMessage.scheduled_time_hour_24h == time[0],
                    DailyScheduledMessage.scheduled_time_minute == time[1],
                )
            )
            .all()
        )

        for message in active_messages_to_send_at_time:
            all_users = session.query(User).filter(User.registered == True).all()
            formatted_message = format_message(
                message.message, message_from=Role.ADMIN, is_prefix=True
            )

            for to_send_user in all_users:
                sent_msg = await context.bot.send_message(
                    chat_id=to_send_user.chat_id, text=formatted_message, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2
                )
                mapping = MessageMapping(
                    sender_message_id=None,
                    sender_chat_id=None,
                    receiver_message_id=sent_msg.message_id,
                    receiver_chat_id=sent_msg.chat_id,
                    message_from=Role.ADMIN,
                )
                session.add(mapping)

            session.commit()

    return execute_jobs_handler


def enqueue_time(context: ContextTypes.DEFAULT_TYPE, time: Tuple[int, int]):
    handler = execute_jobs_at_time_handler(time)
    job_time = datetime.time(hour=time[0], minute=time[1], second=0, tzinfo=TIMEZONE)

    job = context.job_queue.run_daily(
        handler,
        job_time,
    )

    return job


@db_session
async def refresh_scheduled_message_daily(context: ContextTypes.DEFAULT_TYPE, session):
    today_date = datetime.date.today()
    active_messages_for_today = (
        session.query(DailyScheduledMessage)
        .filter(
            and_(
                DailyScheduledMessage.active_from <= today_date,
                DailyScheduledMessage.active_to >= today_date,
            )
        )
        .all()
    )

    scheduled_times = set()

    for message in active_messages_for_today:
        hours = message.scheduled_time_hour_24h
        minute = message.scheduled_time_minute

        time_index = (hours, minute)
        scheduled_times.add(time_index)

    active_job_keys = set(active_jobs_by_time.keys())
    to_add = scheduled_times - active_job_keys
    to_remove = active_job_keys - scheduled_times

    for time in to_add:
        print("Scheduled trigger at {}:{}".format(time[0], time[1]))
        job = enqueue_time(context, time)
        active_jobs_by_time[time] = job

    for time in to_remove:
        print("Removed trigger at {}:{}".format(time[0], time[1]))
        active_jobs_by_time[time].schedule_removal()
        del active_jobs_by_time[time]
