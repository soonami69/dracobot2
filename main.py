import datetime
import logging
import math
import os
import time
from html import escape

from dotenv import load_dotenv
from sqlalchemy import func, or_
from sqlalchemy.orm import scoped_session
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          ConversationHandler, MessageHandler,
                          PicklePersistence, filters)

from dracobot2 import job_handlers
from dracobot2.config import SessionLocal
from dracobot2.models import Role, User
from dracobot2.resources import *
from dracobot2.utils import *
from dracobot2.utils.handles import normalize_telegram_handle
from dracobot2.utils.msg_private import is_message_private
from dracobot2.utils.timezone import TIMEZONE

load_dotenv()


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

TOKEN = os.environ['TELEGRAM_BOT_TOKEN']

UNREGISTERED, MAIN, CHAT, CHAT_LOGIN, DRAGON_CHAT, TRAINER_CHAT, ADMIN_CHAT = range(
    7)

KEYBOARD_OPTIONS = [[DRAGON_CHAT_KEY], [TRAINER_CHAT_KEY],
                    [HELP_KEY, STATUS_KEY], [RULES_KEY, ABOUT_THE_BOT_KEY]]
DEFAULT_REPLY_MARKUP = {'reply_markup': ReplyKeyboardMarkup(
    KEYBOARD_OPTIONS, one_time_keyboard=True)}
REMOVE_REPLY_MARKUP = {'reply_markup': ReplyKeyboardRemove()}

def get_filter_complete_match(match_string):
    return filters.Regex('^' + match_string + '$')

COMMAND_FILTER_REGEX = get_filter_complete_match(ABOUT_THE_BOT_KEY) | get_filter_complete_match(DRAGON_CHAT_KEY) | get_filter_complete_match(TRAINER_CHAT_KEY) | get_filter_complete_match(STATUS_KEY) | get_filter_complete_match(HELP_KEY) | get_filter_complete_match(RULES_KEY)

END = ConversationHandler.END
TIMEOUT = ConversationHandler.TIMEOUT

Session = scoped_session(SessionLocal)

CHAT_TIMEOUT_SECONDS = 2 * 60
TELEGRAM_MESSAGE_MAX_LENGTH = 4096


def get_update_log_context(update):
    if update is None:
        return {"update_id": None}

    message = getattr(update, "effective_message", None)
    user = getattr(update, "effective_user", None)
    chat = getattr(update, "effective_chat", None)

    return {
        "update_id": getattr(update, "update_id", None),
        "chat_id": chat.id if chat else None,
        "chat_type": chat.type if chat else None,
        "user_id": user.id if user else None,
        "username": user.username if user else None,
        "message_id": message.message_id if message else None,
        "message_type": _get_message_type(message),
        "text_preview": _get_text_preview(message),
    }


def _get_message_type(message):
    if message is None:
        return None

    if message.text:
        return "text"
    if message.photo:
        return "photo"
    if message.document:
        return "document"
    if message.video:
        return "video"
    if message.audio:
        return "audio"
    if message.voice:
        return "voice"
    if message.sticker:
        return "sticker"
    if message.video_note:
        return "video_note"
    if message.caption:
        return "caption"

    return "other"


def _get_text_preview(message, limit=80):
    if message is None:
        return None

    text = message.text or message.caption
    if text is None:
        return None

    text = text.replace('\n', '\\n')
    if len(text) > limit:
        return text[:limit] + "..."

    return text


def split_message_text(text, limit=TELEGRAM_MESSAGE_MAX_LENGTH):
    chunks = []
    remaining = text

    while len(remaining) > limit:
        split_at = remaining.rfind('\n', 0, limit + 1)
        if split_at <= 0:
            split_at = limit

        chunk = remaining[:split_at].rstrip()
        chunks.append(chunk)
        remaining = remaining[split_at:].lstrip()

    if remaining:
        chunks.append(remaining)

    return chunks


async def reply_long_text(message, text, **kwargs):
    chunks = split_message_text(text)

    if len(chunks) > 1:
        logger.info(
            "Splitting long Telegram message into %s chunks | chat_id=%s message_id=%s length=%s",
            len(chunks),
            message.chat_id,
            message.message_id,
            len(text),
        )

    for chunk in chunks[:-1]:
        await message.reply_text(chunk)

    if chunks:
        await message.reply_text(chunks[-1], **kwargs)


def db_session(method):
    async def db_session_decorator(*args):
        session = Session()
        update = args[0] if args else None

        try:
            return await method(*args, session)
        except Exception:
            session.rollback()
            logger.exception(
                "Unhandled exception in %s | update=%s",
                method.__name__,
                get_update_log_context(update),
            )
            raise
        finally:
            session.close()
    return db_session_decorator


@db_session
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    user = update.message.from_user
    normalized_username = normalize_telegram_handle(user.username)

    user_filters = [User.chat_id == chat_id]
    if normalized_username is not None:
        user_filters.append(func.lower(User.tele_handle) == normalized_username)

    user_db = session.query(User).filter(or_(*user_filters)).first()

    if user_db is not None:
        is_new_user = not user_db.registered

        if user_db.chat_id != chat_id:
            user_db.chat_id = chat_id
        if not user_db.registered:
            user_db.registered = True

        if normalized_username is not None:
            if user_db.tele_handle != normalized_username:
                logger.info(
                    "Normalizing Telegram handle casing | user_id=%s old_handle=@%s new_handle=@%s",
                    user_db.id,
                    user_db.tele_handle,
                    normalized_username,
                )
            user_db.tele_handle = normalized_username
        user_db.tele_name = user.first_name

        first_name = user.first_name
        if user_db.details:
            first_name = user_db.details.name

        if is_new_user:
            dragon = user_db.dragon
            if dragon and dragon.details and user_db.details:
                logger.info(
                    "Sending new-user welcome message | user_id=%s chat_id=%s dragon_id=%s",
                    user_db.id,
                    chat_id,
                    dragon.id,
                )
                welcome_message = WELCOME_MESSAGE.format(**{
                    'name': escape(user_db.details.name or ""),
                    'dragon_name': escape(dragon.details.name or ""),
                })
                messages = list(filter(lambda x: len(x) > 0, welcome_message.split('\n\n\n')))
                for message in messages:
                    await update.message.reply_text(message, parse_mode=telegram.constants.ParseMode.HTML)
                    time.sleep(math.ceil(len(message) / 40) + 1)

            else:
                logger.warning(
                    "Newly registered user is missing dragon/details for welcome message | user_id=%s chat_id=%s has_dragon=%s has_user_details=%s",
                    user_db.id,
                    chat_id,
                    dragon is not None,
                    user_db.details is not None,
                )
                await update.message.reply_text(USER_NO_DRAGON)

        session.commit()

        await update.message.reply_text(HELLO_GREETING.format(
            first_name), **DEFAULT_REPLY_MARKUP)

        return MAIN
    else:
        logger.warning(
            "Unregistered user attempted to start bot | chat_id=%s username=%s user_id=%s",
            chat_id,
            user.username,
            user.id,
        )
        await update.message.reply_text(USER_UNREGISTERED)

        if user.username is None:
            logger.warning("Telegram user has no username/handle | chat_id=%s user_id=%s", chat_id, user.id)
            await update.message.reply_text(USER_NO_TELE_HANDLE)

        return UNREGISTERED


async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(ABOUT_THE_BOT, **DEFAULT_REPLY_MARKUP)

    return MAIN


@db_session
async def helps(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    user = update.message.from_user
    chat_id = update.message.chat_id

    user_db = session.query(User).filter(User.chat_id == chat_id).first()

    if user_db is None:
        logger.warning("Help requested by unknown chat | chat_id=%s user_id=%s username=%s", chat_id, user.id, user.username)
        await update.message.reply_text(USER_UNREGISTERED)
        return UNREGISTERED

    first_name = user.first_name
    if user_db.details:
        first_name = user_db.details.name

    await update.message.reply_text(HELP_MESSAGE.format(
        escape(first_name or "")), parse_mode=telegram.constants.ParseMode.HTML, **DEFAULT_REPLY_MARKUP)

    return MAIN


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(GAME_RULES_MESSAGE, parse_mode=telegram.constants.ParseMode.HTML, **DEFAULT_REPLY_MARKUP)

    return MAIN


@db_session
async def status(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    cur_user = session.query(User).filter(User.chat_id == chat_id).first()

    if cur_user is None:
        logger.warning("Status requested by unknown chat | chat_id=%s", chat_id)
        await update.message.reply_text(USER_UNREGISTERED)
        return UNREGISTERED

    trainer = session.query(User).filter(User.dragon_id == cur_user.id).first()
    dragon = session.query(User).filter(User.id == cur_user.dragon_id).first()

    dragon_details = None
    if dragon and dragon.details:
        dragon_details = {
            'name': dragon.details.name,
            'likes': dragon.details.likes,
            'dislikes': dragon.details.dislikes,
            'room_number': dragon.details.room_number,
            'requests': dragon.details.requests,
            'level': dragon.details.level
        }

    trainer_details = None
    if trainer and trainer.details:
        trainer_details = {
            'name': trainer.details.name,
            'room_number': trainer.details.room_number,
        }

    t_registered = format_registered_message(trainer)
    d_registered = format_registered_message(dragon)

    message = STATUS.format(**{
        'trainer_status': t_registered,
        'dragon_status': d_registered
    })

    # if trainer_details is not None:
    #     message += '\n' + TRAINER_DETAILS.format(**trainer_details)

    if dragon_details is not None:
        message += '\n' + DRAGON_DETAILS.format(**dragon_details)

    logger.info(
        "Status requested | user_id=%s chat_id=%s trainer_id=%s dragon_id=%s status_length=%s",
        cur_user.id,
        chat_id,
        trainer.id if trainer else None,
        dragon.id if dragon else None,
        len(message),
    )
    await reply_long_text(update.message, message, **DEFAULT_REPLY_MARKUP)

    return MAIN


@db_session
async def check_trainer(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    cur_user = session.query(User).filter(User.chat_id == chat_id).first()

    if cur_user is None:
        logger.warning("Trainer chat requested by unknown chat | chat_id=%s", chat_id)
        await update.message.reply_text(USER_UNREGISTERED, **DEFAULT_REPLY_MARKUP)
        return END

    cur_user_id = cur_user.id

    trainer = session.query(User).filter(User.dragon_id == cur_user_id).first()

    if trainer is None:
        logger.warning("Trainer chat requested but no trainer assigned | user_id=%s chat_id=%s", cur_user.id, chat_id)
        await update.message.reply_text(USER_NO_TRAINER, **DEFAULT_REPLY_MARKUP)
        return END
    elif not trainer.registered:
        logger.info(
            "Trainer chat requested but trainer is unregistered | user_id=%s trainer_id=%s chat_id=%s",
            cur_user.id,
            trainer.id,
            chat_id,
        )
        await update.message.reply_text(
            USER_UNREGISTERED_TRAINER, **DEFAULT_REPLY_MARKUP)
        return END
    else:
        await update.message.reply_text(
            CONNECTION_SUCCESS.format(TRAINER_KEY), **REMOVE_REPLY_MARKUP)
        return TRAINER_CHAT


@db_session
async def check_dragon(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    cur_user = session.query(User).filter(User.chat_id == chat_id).first()

    if cur_user is None:
        logger.warning("Dragon chat requested by unknown chat | chat_id=%s", chat_id)
        await update.message.reply_text(USER_UNREGISTERED, **DEFAULT_REPLY_MARKUP)
        return END

    dragon_id = cur_user.dragon_id

    dragon = session.query(User).filter(User.id == dragon_id).first()

    if dragon is None:
        logger.warning("Dragon chat requested but no dragon assigned | user_id=%s chat_id=%s", cur_user.id, chat_id)
        await update.message.reply_text(USER_NO_DRAGON, **DEFAULT_REPLY_MARKUP)
        return END
    elif not dragon.registered:
        logger.info(
            "Dragon chat requested but dragon is unregistered | user_id=%s dragon_id=%s chat_id=%s",
            cur_user.id,
            dragon.id,
            chat_id,
        )
        await update.message.reply_text(
            USER_UNREGISTERED_DRAGON, **DEFAULT_REPLY_MARKUP)
        return END
    else:
        await update.message.reply_text(
            CONNECTION_SUCCESS.format(DRAGON_KEY), **REMOVE_REPLY_MARKUP)
        return DRAGON_CHAT


@db_session
async def check_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    user_db = session.query(User).filter(User.chat_id == chat_id).first()

    if user_db and user_db.is_admin:
        logger.info("Admin mode started | user_id=%s chat_id=%s", user_db.id, chat_id)
        await update.message.reply_text(ADMIN_GREETING, **REMOVE_REPLY_MARKUP)
        return ADMIN_CHAT

    logger.warning(
        "Admin mode rejected | chat_id=%s user_id=%s is_registered=%s",
        chat_id,
        user_db.id if user_db else None,
        user_db is not None,
    )
    await update.message.reply_text(UNKNOWN_COMMAND)
    return END


async def send_message_to_dragon(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    cur_user = session.query(User).filter(User.chat_id == chat_id).first()

    if cur_user is None:
        logger.warning("Message to dragon rejected because sender is unknown | chat_id=%s", chat_id)
        await update.message.reply_text(USER_UNREGISTERED, **DEFAULT_REPLY_MARKUP)
        return END

    dragon_id = cur_user.dragon_id

    dragon = session.query(User).filter(User.id == dragon_id).first()

    if not is_message_private(update.message):
        logger.warning(
            "Message to dragon rejected as non-private media | user_id=%s chat_id=%s message_id=%s message_type=%s",
            cur_user.id,
            chat_id,
            update.message.message_id,
            _get_message_type(update.message),
        )
        await update.message.reply_text(NON_PRIVATE_MESSAGE, reply_to_message_id=update.message.message_id, **REMOVE_REPLY_MARKUP)
        return DRAGON_CHAT

    if dragon is not None:
        logger.info(
            "Forwarding message to dragon | sender_id=%s receiver_id=%s sender_chat_id=%s receiver_chat_id=%s message_id=%s message_type=%s",
            cur_user.id,
            dragon.id,
            chat_id,
            dragon.chat_id,
            update.message.message_id,
            _get_message_type(update.message),
        )
        await forward_message(update.message, dragon.chat_id,
                        context.bot, session, message_from=Role.TRAINER)
        return DRAGON_CHAT
    else:
        logger.warning("Message to dragon failed because no dragon user exists | user_id=%s chat_id=%s", cur_user.id, chat_id)
        await update.message.reply_text(CONNECTION_ERROR, **REMOVE_REPLY_MARKUP)
        return END


async def send_message_to_trainer(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    cur_user = session.query(User).filter(User.chat_id == chat_id).first()

    if cur_user is None:
        logger.warning("Message to trainer rejected because sender is unknown | chat_id=%s", chat_id)
        await update.message.reply_text(USER_UNREGISTERED, **DEFAULT_REPLY_MARKUP)
        return END

    cur_user_id = cur_user.id

    trainer = session.query(User).filter(User.dragon_id == cur_user_id).first()

    if trainer is not None:
        logger.info(
            "Forwarding message to trainer | sender_id=%s receiver_id=%s sender_chat_id=%s receiver_chat_id=%s message_id=%s message_type=%s",
            cur_user.id,
            trainer.id,
            chat_id,
            trainer.chat_id,
            update.message.message_id,
            _get_message_type(update.message),
        )
        await forward_message(update.message, trainer.chat_id,
                        context.bot, session, message_from=Role.DRAGON)
        return TRAINER_CHAT
    else:
        logger.warning("Message to trainer failed because no trainer user exists | user_id=%s chat_id=%s", cur_user.id, chat_id)
        await update.message.reply_text(CONNECTION_ERROR, **REMOVE_REPLY_MARKUP)
        return END


@db_session
async def send_trainer(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    return await send_message_to_trainer(update, context, session)


@db_session
async def send_dragon(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    return await send_message_to_dragon(update, context, session)


@db_session
async def send_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    chat_id = update.message.chat_id
    user_db = session.query(User).filter(User.chat_id == chat_id).first()

    if user_db is None or not user_db.is_admin:
        logger.warning(
            "Admin broadcast rejected | chat_id=%s user_id=%s is_admin=%s",
            chat_id,
            user_db.id if user_db else None,
            user_db.is_admin if user_db else False,
        )
        return END

    all_users = session.query(User).filter(User.registered == True).all()
    logger.info(
        "Admin broadcast started | admin_user_id=%s chat_id=%s recipients=%s message_id=%s message_type=%s",
        user_db.id,
        chat_id,
        max(len(all_users) - 1, 0),
        update.message.message_id,
        _get_message_type(update.message),
    )

    for to_send_user in all_users:
        if to_send_user.id != user_db.id:
            await forward_message(update.message, to_send_user.chat_id,
                            context.bot, session, message_from=Role.ADMIN)

    return ADMIN_CHAT


def handle_reply_message(current_mode):
    @db_session
    async def inner_reply_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
        new_mode = check_reply_mapping(update.message, session)
        ret_value = END

        if new_mode == Role.TRAINER or (new_mode is None and current_mode == Role.TRAINER):
            ret_value = await send_message_to_trainer(update, context, session)
        elif new_mode == Role.DRAGON or (new_mode is None and current_mode == Role.DRAGON):
            ret_value = await send_message_to_dragon(update, context, session)

        if new_mode is not None:
            if current_mode is None:
                await update.message.reply_text(USER_REPLY_SHORTCUT.format(
                    TRAINER_KEY if new_mode == Role.TRAINER else DRAGON_KEY), **REMOVE_REPLY_MARKUP),
            elif current_mode != new_mode:
                await update.message.reply_text(USER_REPLY_CHANGE_MODE.format(
                    TRAINER_KEY if new_mode == Role.TRAINER else DRAGON_KEY), **REMOVE_REPLY_MARKUP)

        return ret_value
    return inner_reply_message


@db_session
async def handle_edited_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    logger.info("Edited message received | update=%s", get_update_log_context(update))
    await edit_message(update, context, session)


@db_session
async def handle_delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    logger.info("Delete message requested | update=%s", get_update_log_context(update))
    await delete_message_reply(update.message, context.bot, session)


async def unknown_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(UNKNOWN_COMMAND)


def handle_unknown_message_chat(target):
    async def unknown_message_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(UNKNOWN_CHAT_COMMAND.format(target))
    return unknown_message_chat


@db_session
async def handle_delete_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, session):
    if len(context.args) == 2:
        chat_id, message_id = context.args
        await delete_message(update.message, message_id,
                       chat_id, None, context.bot, session)
    else:
        await delete_message_reply(update.message, context.bot, session)
    return ADMIN_CHAT


async def unsupported_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.warning("Unsupported media received | update=%s", get_update_log_context(update))
    await update.message.reply_text(
        UNSUPPORTED_MEDIA, reply_to_message_id=update.message.message_id, **REMOVE_REPLY_MARKUP)


async def handle_timeout_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    timeout_message = ""
    if CHAT_TIMEOUT_SECONDS < 60:
        timeout_message = str(CHAT_TIMEOUT_SECONDS) + " second(s)"
    else:
        timeout_message = str(CHAT_TIMEOUT_SECONDS // 60) + " minutes(s)"

    await update.message.reply_text(TIMEOUT_MESSAGE.format(timeout_message), **DEFAULT_REPLY_MARKUP)

    return END


def done_chat(target):
    async def inner_done_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            CHAT_COMPLETE.format(target), **DEFAULT_REPLY_MARKUP)

        return END
    return inner_done_chat


async def _error(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exc_info = None
    if context.error is not None:
        exc_info = (type(context.error), context.error, context.error.__traceback__)

    logger.error(
        "Unhandled Telegram application error | update=%s error=%s",
        get_update_log_context(update),
        context.error,
        exc_info=exc_info,
    )


def main():
    # Create the Updater and pass it your bot's token.
    # Make sure to set use_context=True to use the new context based callbacks
    # Post version 12 this will no longer be necessary
    pp = PicklePersistence('conversationbot')
    application = Application.builder().token(TOKEN).persistence(pp).build()

    chat_handler = ConversationHandler(
        entry_points=[MessageHandler(get_filter_complete_match(DRAGON_CHAT_KEY), check_dragon),
                      CommandHandler(DRAGON_KEY, check_dragon),
                      MessageHandler(get_filter_complete_match(
                          TRAINER_CHAT_KEY), check_trainer),
                      CommandHandler(TRAINER_KEY, check_trainer),
                      MessageHandler(filters.REPLY, handle_reply_message(None)), ],

        states={
            # Chat with dragon
            DRAGON_CHAT: [MessageHandler(filters.UpdateType.EDITED_MESSAGE,
                                         handle_edited_message),
                          CommandHandler(DONE_KEY, done_chat(DRAGON_KEY)),
                          CommandHandler(DELETE_KEY, handle_delete_message),
                          MessageHandler(
                              filters.COMMAND | COMMAND_FILTER_REGEX, handle_unknown_message_chat(DRAGON_KEY)),
                          MessageHandler(
                              filters.REPLY, handle_reply_message(Role.DRAGON)),
                          MessageHandler(
                              SUPPORTED_MESSAGE_FILTERS, send_dragon),
                          MessageHandler(UNSUPPORTED_MESSAGE_FILTERS, unsupported_media)],

            # Chat with trainer
            TRAINER_CHAT: [MessageHandler(filters.UpdateType.EDITED_MESSAGE,
                                          handle_edited_message),
                           CommandHandler(DONE_KEY, done_chat(TRAINER_KEY)),
                           CommandHandler(DELETE_KEY, handle_delete_message),
                           MessageHandler(
                               filters.COMMAND | COMMAND_FILTER_REGEX, handle_unknown_message_chat(TRAINER_KEY)),
                           MessageHandler(
                               filters.REPLY, handle_reply_message(Role.TRAINER)),
                           MessageHandler(
                               SUPPORTED_MESSAGE_FILTERS, send_trainer),
                           MessageHandler(UNSUPPORTED_MESSAGE_FILTERS, unsupported_media)],

            TIMEOUT: [MessageHandler(
                filters.TEXT | filters.COMMAND, handle_timeout_chat)]
        },

        fallbacks=[],
        conversation_timeout=CHAT_TIMEOUT_SECONDS,
        map_to_parent={
            END: MAIN,
        },

        name="dt_conversation",
        persistent=True,
    )

    admin_handler = ConversationHandler(
        entry_points=[CommandHandler(ADMIN_KEY, check_admin)],

        states={
            ADMIN_CHAT: [MessageHandler(filters.UpdateType.EDITED_MESSAGE,
                                        handle_edited_message),
                         CommandHandler(DONE_KEY, done_chat(ADMIN_KEY)),
                         CommandHandler(DELETE_KEY, handle_delete_admin, block=False),
                         MessageHandler(
                             filters.COMMAND | COMMAND_FILTER_REGEX, handle_unknown_message_chat(ADMIN_KEY)),
                         MessageHandler(SUPPORTED_MESSAGE_FILTERS, send_admin, block=False),
                         MessageHandler(UNSUPPORTED_MESSAGE_FILTERS, unsupported_media)],

            TIMEOUT: [MessageHandler(
                filters.TEXT | filters.COMMAND, handle_timeout_chat)]
        },

        fallbacks=[],
        conversation_timeout=CHAT_TIMEOUT_SECONDS,
        map_to_parent={
            END: MAIN,
        },

        name="admin_conversation",
        persistent=True,
    )

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message),
                      MessageHandler(filters.ALL, start, block=False), ],

        states={
            UNREGISTERED: [MessageHandler(filters.ALL, start, block=False)],

            MAIN: [MessageHandler(filters.UpdateType.EDITED_MESSAGE, handle_edited_message),
                   chat_handler,
                   admin_handler,
                   CommandHandler(START_KEY, start),
                   CommandHandler(MENU_KEY, start),
                   CommandHandler(DELETE_KEY, handle_delete_message),
                   CommandHandler(ABOUT_COMMAND_KEY, about),
                   CommandHandler(HELP_COMMAND_KEY, helps),
                   CommandHandler(RULES_COMMAND_KEY, rules),
                   CommandHandler(STATUS_COMMAND_KEY, status),
                   MessageHandler(get_filter_complete_match(ABOUT_THE_BOT_KEY), about),
                   MessageHandler(get_filter_complete_match(HELP_KEY), helps),
                   MessageHandler(get_filter_complete_match(RULES_KEY), rules),
                   MessageHandler(get_filter_complete_match(STATUS_KEY), status)],
        },

        fallbacks=[MessageHandler(filters.ALL, unknown_message)],

        name="main_conversation",
        persistent=True,
    )

    application.add_error_handler(_error, block=False)
    application.add_handler(conv_handler)

    application.job_queue.run_once(job_handlers.refresh_scheduled_message_daily, 0, job_kwargs={"misfire_grace_time": None})

    refresh_time = datetime.time(hour=0, minute=0, second=0, tzinfo=TIMEZONE)
    application.job_queue.run_daily(job_handlers.refresh_scheduled_message_daily, refresh_time, job_kwargs={"misfire_grace_time": None})

    # Start the Bot
    application.run_polling()


if __name__ == '__main__':
    logger.info("Initialised....")
    logger.info("Starting main()...")
    main()
