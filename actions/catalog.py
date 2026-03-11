import os
import shutil
import tempfile
import uuid
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel

from rasa.nlu.utils import write_json_to_file
from rasa.shared.utils.io import read_json_file

ORIGIN_DB_PATH = "db"
CATALOG = "catalog.json"
ORDERS = "orders.json"


class Book(BaseModel):
    id: str
    title: str
    description: str
    pages: int
    price: int
    currency: str
    preview: str
    download_link: str


class Order(BaseModel):
    order_id: str
    book_id: str
    book_title: str
    buyer_name: str
    screenshot_url: str
    created_at: str


def get_session_db_path(session_id: str) -> str:
    tempdir = tempfile.gettempdir()
    return os.path.join(tempdir, "ebook_bot", session_id)


def prepare_db_file(session_id: str, db: str) -> str:
    session_db_path = get_session_db_path(session_id)
    os.makedirs(session_db_path, exist_ok=True)
    destination_file = os.path.join(session_db_path, db)
    if not os.path.exists(destination_file):
        origin_file = os.path.join(ORIGIN_DB_PATH, db)
        shutil.copy(origin_file, destination_file)
    return destination_file


def read_db(session_id: str, db: str) -> Any:
    db_file = prepare_db_file(session_id, db)
    return read_json_file(db_file)


def write_db(session_id: str, db: str, data: Any) -> None:
    db_file = prepare_db_file(session_id, db)
    write_json_to_file(db_file, data)


def get_all_books(session_id: str) -> List[Book]:
    return [Book(**item) for item in read_db(session_id, CATALOG)]


def get_book_by_id(session_id: str, book_id: str) -> Optional[Book]:
    books = get_all_books(session_id)
    for book in books:
        if book.id == book_id:
            return book
    return None


def create_order(session_id: str, book_id: str, book_title: str, buyer_name: str, screenshot_url: str) -> Order:
    raw_orders = read_db(session_id, ORDERS)
    order = Order(
        order_id=str(uuid.uuid4())[:8].upper(),
        book_id=book_id,
        book_title=book_title,
        buyer_name=buyer_name,
        screenshot_url=screenshot_url,
        created_at=datetime.utcnow().isoformat(),
    )
    raw_orders.append(order.dict())
    write_db(session_id, ORDERS, raw_orders)
    return order
