import os
from datetime import datetime,timezone
from sqlalchemy import create_engine,String,Integer,JSON,DateTime,ForeignKey,UniqueConstraint,event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase,Mapped,mapped_column,sessionmaker
from dotenv import load_dotenv
load_dotenv()
URL=os.getenv('DATABASE_URL','sqlite:///./monetize360_v2.db')
engine=create_engine(URL,connect_args={'check_same_thread':False,'timeout':30} if URL.startswith('sqlite') else {},pool_pre_ping=True)
if URL.startswith('sqlite'):
    @event.listens_for(engine,'connect')
    def sqlite_options(connection,record):
        connection.execute('PRAGMA foreign_keys=ON')
Session=sessionmaker(engine,expire_on_commit=False)
Doc=JSON().with_variant(JSONB,'postgresql')
def now():return datetime.now(timezone.utc)
class Base(DeclarativeBase):
    """Schema base."""
class StrategyRecord(Base):
    __tablename__='strategies'
    id:Mapped[str]=mapped_column(String(50),primary_key=True)
    name:Mapped[str]=mapped_column(String(80))
    active_version:Mapped[int|None]=mapped_column(Integer,nullable=True)
class Version(Base):
    __tablename__='strategy_versions'
    __table_args__=(UniqueConstraint('strategy_id','version'),)
    id:Mapped[int]=mapped_column(primary_key=True)
    strategy_id:Mapped[str]=mapped_column(ForeignKey('strategies.id'))
    version:Mapped[int]=mapped_column(Integer)
    config:Mapped[dict]=mapped_column(Doc)
    config_hash:Mapped[str]=mapped_column(String(64))
    status:Mapped[str]=mapped_column(String(20),default='draft')
    validation:Mapped[dict|None]=mapped_column(Doc,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Product(Base):
    __tablename__='products'
    id:Mapped[str]=mapped_column(String(50),primary_key=True)
    strategy_id:Mapped[str]=mapped_column(ForeignKey('strategies.id'))
    data:Mapped[dict]=mapped_column(Doc)
class Decision(Base):
    __tablename__='decisions'
    id:Mapped[int]=mapped_column(primary_key=True)
    product_id:Mapped[str]=mapped_column(String(50),index=True)
    strategy_id:Mapped[str]=mapped_column(String(50),index=True)
    version:Mapped[int]=mapped_column(Integer)
    product_snapshot:Mapped[dict]=mapped_column(Doc)
    request:Mapped[dict]=mapped_column(Doc)
    result:Mapped[dict]=mapped_column(Doc)
    request_hash:Mapped[str]=mapped_column(String(64))
    idempotency_key:Mapped[str|None]=mapped_column(String(120),unique=True,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now,index=True)
class Simulation(Base):
    __tablename__='simulations'
    id:Mapped[int]=mapped_column(primary_key=True)
    request:Mapped[dict]=mapped_column(Doc)
    result:Mapped[dict]=mapped_column(Doc)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Audit(Base):
    __tablename__='audit_events'
    id:Mapped[int]=mapped_column(primary_key=True)
    actor:Mapped[str]=mapped_column(String(30))
    action:Mapped[str]=mapped_column(String(50))
    entity:Mapped[str]=mapped_column(String(80))
    detail:Mapped[dict]=mapped_column(Doc)
    created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
