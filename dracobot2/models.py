import enum

from sqlalchemy import (Boolean, Column, Date, ForeignKey, Integer, String,
                        UnicodeText)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import backref, relationship
from sqlalchemy.types import Enum

Base = declarative_base()


class Role(enum.Enum):
    DRAGON = 1
    TRAINER = 2
    ADMIN = 3


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    chat_id = Column(Integer, unique=True)
    tele_handle = Column(String(25), nullable=False, unique=True)
    tele_name = Column(String(100))
    dragon_id = Column(Integer, ForeignKey('users.id'), index=True)
    # ref: https://github.com/sqlalchemy/sqlalchemy/issues/1403#issue-384617192
    registered = Column(Boolean, nullable=False,
                        default=False, server_default="0")
    is_admin = Column(Boolean, nullable=False,
                        default=False, server_default="0")
    dragon = relationship('User', remote_side=[id], backref=backref(
        'trainer', uselist=False), uselist=False, post_update=True)
    details = relationship('UserDetails', uselist=False, back_populates='user', lazy='joined')


class UserDetails(Base):
    __tablename__ = 'user_details'

    user_id = Column(Integer, ForeignKey(User.id),
                     primary_key=True, nullable=False)
    name = Column(String(100))
    likes = Column(UnicodeText)
    dislikes = Column(UnicodeText)
    room_number = Column(String(7))
    requests = Column(UnicodeText)
    level = Column(Integer)
    user = relationship('User', back_populates='details')


class MessageMapping(Base):
    __tablename__ = 'message_mapping'

    sender_message_id = Column(Integer, nullable=True)
    sender_chat_id = Column(Integer, nullable=True)
    receiver_message_id = Column(Integer, primary_key=True, nullable=False)
    receiver_chat_id = Column(Integer, primary_key=True, nullable=False)
    receiver_caption_message_id = Column(Integer, nullable=True)
    deleted = Column(Boolean, nullable=False,
                     default=False, server_default="0")
    message_from = Column(Enum(Role), nullable=False)


class DailyScheduledMessage(Base):
    __tablename__ = 'daily_scheduled_message'

    id = Column(Integer, primary_key=True)
    scheduled_time_hour_24h = Column(Integer, nullable=False)
    scheduled_time_minute = Column(Integer, nullable=False)
    message = Column(Integer, nullable=False)
    active_from = Column(Date, nullable=False)
    active_to = Column(Date, nullable=False)
