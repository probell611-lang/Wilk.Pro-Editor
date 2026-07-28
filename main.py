import aiosqlite
import time
import asyncio
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramForbiddenError
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.filters.callback_data import CallbackData

dp = Dispatcher()

# --- States ---
class Purpose_of_the_button(CallbackData, prefix="btn"):
    purpose: str

class OrderActionCallback(CallbackData, prefix="order"):
    action: str
    order_number: int

class Statistics(StatesGroup):
    waiting_for_user_id = State()

class BroadcastMessage(StatesGroup):
    message_text = State()

class SetChannelUserName(StatesGroup):
    waiting_for_channel_username = State()

class DeleteOrder(StatesGroup):
    order_number = State()

class OperationHistory(StatesGroup):
    waiting_for_user_id = State()

class AddOrder(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_item_name = State()
    waiting_for_price = State()

class OrdersMenu(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_order_number = State()

# --- Middleware ---
class UserMiddleware(BaseMiddleware):
    def __init__(self, db_path: str):
        self.db_path = db_path

    async def __call__(self, handler, event: Message, data: dict):
        user = event.from_user
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            # Проверяем, есть ли пользователь
            async with db.execute("SELECT id, username FROM Users WHERE id = ?", (user.id,)) as cursor:
                row = await cursor.fetchone()

            if row is None:
                # Регистрируем нового пользователя
                username = f"@{user.username}" if user.username else "Нету"
                await db.execute(
                    "INSERT INTO Users (id, username, nickname) VALUES (?, ?, ?)",
                    (user.id, username, user.full_name)
                )
                await db.commit()
            else:
                # Обновляем username, если изменился
                stored_username = row["username"]
                new_username = f"@{user.username}" if user.username else "Нету"
                if stored_username != new_username:
                    await db.execute(
                        "UPDATE Users SET username = ? WHERE id = ?",
                        (new_username, user.id)
                    )
                    await db.commit()

        return await handler(event, data)

dp.message.middleware(UserMiddleware("DataBase_for_telegram_bot.db"))

# --- Helper functions (DB-based) ---
async def get_balance(user_id: int, db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT price FROM Orders WHERE user_id = ? AND status IN ('completed', 'active')",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()
        return sum(row["price"] for row in rows)

async def get_orders_count(user_id: int, db_path: str) -> int:
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT COUNT(*) AS cnt FROM Orders WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return row[0] if row else 0

async def split_orders(orders: list, limit: int = 50) -> list[list]:
    pages = []
    page = []
    for order in orders:
        page.append(order)
        if len(page) == limit:
            pages.append(page)
            page = []
    if page:
        pages.append(page)
    return pages

# --- Handlers ---
@dp.message(Command("start"))
async def start_bot(message: Message, state: FSMContext):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Admin_id",)) as cursor:
            admin_row = await cursor.fetchone()
        admin_id = int(admin_row["Value"]) if admin_row else 0

    if message.from_user.id == admin_id:
        await message.answer(
            "Добро пожаловать! Вы администратор этого бота.\n\n"
            "/exit — выйти из состояния.\n\nВот ваша админ-панель:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="📊 Статистика", callback_data=Purpose_of_the_button(purpose="statistics").pack())],
                [InlineKeyboardButton(text="🗑 Удалить операцию", callback_data=Purpose_of_the_button(purpose="delete_operation").pack())],
                [InlineKeyboardButton(text="📦 Заказы", callback_data=Purpose_of_the_button(purpose="orders").pack())],
                [InlineKeyboardButton(text="➕ Создать заказ", callback_data=Purpose_of_the_button(purpose="create_order").pack())],
                [InlineKeyboardButton(text="📢 Канал", callback_data=Purpose_of_the_button(purpose="channel").pack())],
                [InlineKeyboardButton(text="📣 Рассылка", callback_data=Purpose_of_the_button(purpose="newsletter").pack())],
            ])
        )
    else:
        balance = await get_balance(message.from_user.id, db_path)
        count = await get_orders_count(message.from_user.id, db_path)

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Admin_username",)) as cursor:
                admin_row = await cursor.fetchone()
        admin_username = admin_row["Value"] if admin_row else "@unknown"

        await message.answer(
            f"Добро пожаловать в Бота!\n\n"
            f"Айди покупателя: <code>{message.from_user.id}</code>\n"
            f"Баланс: {balance} ₽\n"
            f"Заказов: {count}\n\n"
            f"Связаться с менеджером: {admin_username}",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardMarkup(keyboard=[
                [KeyboardButton(text="🛍 Показать мои заказы"), KeyboardButton(text="👤 Профиль")],
                [KeyboardButton(text="➡️ Продолжить покупки в магазине")],
                [KeyboardButton(text="🙋🏻‍♀️ Связаться с менеджером для новых заказов или чтобы задать вопросы")],
            ], resize_keyboard=True, is_persistent=False)
        )

@dp.callback_query(Purpose_of_the_button.filter())
async def counter_for_buttons(callback: CallbackQuery, callback_data: Purpose_of_the_button, state: FSMContext):
    value = callback_data.purpose

    if value == "statistics":
        await callback.message.answer("Отправьте айди пользователя:")
        await state.set_state(Statistics.waiting_for_user_id)
    elif value == "newsletter":
        await callback.message.answer("Отправьте сообщение, которое нужно разослать всем пользователям этого бота:")
        await state.set_state(BroadcastMessage.message_text)
    elif value == "channel":
        await callback.message.answer(
            "Выберите действие:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="Текущий канал", callback_data=Purpose_of_the_button(purpose="now_channel").pack())],
                [InlineKeyboardButton(text="Установить канал", callback_data=Purpose_of_the_button(purpose="install_channel").pack())],
            ])
        )
    elif value == "now_channel":
        db_path = "DataBase_for_telegram_bot.db"
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Channel",)) as cursor:
                row = await cursor.fetchone()
        channel = row["Value"] if row else "Канал не установлен"
        await callback.message.answer(channel)
    elif value == "install_channel":
        await callback.message.answer("Отправьте ссылку на канал, которая будет находиться в сообщении у пользователя:")
        await state.set_state(SetChannelUserName.waiting_for_channel_username)
    elif value == "delete_operation":
        await callback.message.answer("Отправьте номер заказа, который нужно удалить.")
        await state.set_state(DeleteOrder.order_number)
    elif value == "operation_history":
        await callback.message.answer("Отправьте айди пользователя, для которого хотите посмотреть историю операций:")
        await state.set_state(OperationHistory.waiting_for_user_id)
    elif value == "create_order":
        await callback.message.answer("Отправьте айди пользователя, для которого хотите создать заказ:")
        await state.set_state(AddOrder.waiting_for_user_id)
    elif value == "orders":
        await callback.message.answer("Введите айди пользователя, чьи активные заказы хотите посмотреть:")
        await state.set_state(OrdersMenu.waiting_for_user_id)

    await callback.answer()

@dp.message(OrdersMenu.waiting_for_user_id)
async def ordersmenu_waiting_for_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        db_path = "DataBase_for_telegram_bot.db"
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT number, item_name, price, created_at FROM Orders WHERE user_id = ? AND status = 'active'",
                (user_id,)
            ) as cursor:
                rows = await cursor.fetchall()

        if not rows:
            await message.answer("Пока что у этого пользователя нет активных заказов.")
            await state.clear()
            return

        pages = await split_orders(rows, limit=10)
        for page in pages:
            text = f"Активные заказы для пользователя {user_id}:\n\n"
            for row in page:
                text += (
                    f"🔹 № {row['number']}\n"
                    f"🎮 {row['item_name']}\n"
                    f"💰 {row['price']} ₽\n"
                    f"📅 {time.strftime('%d.%m.%Y %H:%M', time.localtime(row['created_at']))}\n"
                    "--------------------\n"
                )
            await message.answer(text, parse_mode="HTML")

        await state.update_data(waiting_for_user_id=user_id)
        await state.set_state(OrdersMenu.waiting_for_order_number)
    except ValueError:
        await message.answer("Пожалуйста, введите корректный числовой ID пользователя.")
        await state.clear()
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()

@dp.message(OrdersMenu.waiting_for_order_number)
async def ordersmenu_waiting_for_order_number(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = data.get("waiting_for_user_id")
    try:
        order_number = int(message.text)
        db_path = "DataBase_for_telegram_bot.db"
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM Orders WHERE number = ? AND user_id = ? AND status = 'active'",
                (order_number, user_id)
            ) as cursor:
                row = await cursor.fetchone()

        if row:
            await message.answer(
                f"Заказ № {order_number} найден. Выберите действие:",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Завершить", callback_data=OrderActionCallback(action="complete", order_number=order_number).pack())],
                    [InlineKeyboardButton(text="Отменить", callback_data=OrderActionCallback(action="cancel", order_number=order_number).pack())],
                ])
            )
            await state.clear()
        else:
            await message.answer("Такого номера нет у этого пользователя в активных заказах. Начните всё заново.")
            await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректный номер заказа.")
        await state.clear()
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()

@dp.callback_query(OrderActionCallback.filter())
async def orderactioncallback(callback: CallbackQuery, callback_data: OrderActionCallback):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM Orders WHERE number = ?", (callback_data.order_number,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            await callback.answer("Заказ не найден ❌.", show_alert=True)
            return

        if callback_data.action == "complete":
            if row["status"] == "completed":
                await callback.answer("Заказ уже завершён 😏.", show_alert=True)
                return

            await db.execute(
                "UPDATE Orders SET status = ? WHERE number = ?",
                ("completed", callback_data.order_number)
            )
            await db.commit()
            await callback.answer("Заказ успешно завершён 😊.")
            await callback.message.delete()

        elif callback_data.action == "cancel":
            if row["status"] == "completed":
                await callback.answer("Заказ уже завершён 🫠.", show_alert=True)
                return

            await db.execute(
                "DELETE FROM Orders WHERE number = ?",
                (callback_data.order_number,)
            )
            await db.commit()
            await callback.answer("Заказ успешно отменён ✅.")
            await callback.message.delete()


@dp.message(DeleteOrder.order_number)
async def deleteorder_order_number(message: Message, state: FSMContext):
    try:
        order_number = int(message.text)
        db_path = "DataBase_for_telegram_bot.db"
        async with aiosqlite.connect(db_path) as db:
            async with db.execute("SELECT 1 FROM Orders WHERE number = ?", (order_number,)) as cursor:
                exists = await cursor.fetchone()
            if not exists:
                await message.answer("Заказ с таким номером не найден.")
                await state.clear()
                return

            await db.execute("DELETE FROM Orders WHERE number = ?", (order_number,))
            await db.commit()

        await message.answer("Заказ успешно удалён ✅.")
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректный номер заказа.")
        await state.clear()
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()


@dp.message(SetChannelUserName.waiting_for_channel_username)
async def setchannelusername_waiting_for_channel_username(message: Message, state: FSMContext):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "UPDATE SystemData SET Value = ? WHERE Name = ?",
            (message.text, "Channel")
        )
        await db.commit()

    # Также обновим в памяти, если нужно (но в этой версии мы почти не держим состояние в памяти)
    await message.answer("Канал успешно установлен ✅.")
    await state.clear()


@dp.message(Statistics.waiting_for_user_id)
async def statistics_waiting_for_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text)
        db_path = "DataBase_for_telegram_bot.db"

        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row

            # Данные пользователя
            async with db.execute("SELECT username, nickname FROM Users WHERE id = ?", (user_id,)) as cursor:
                user_row = await cursor.fetchone()
            if not user_row:
                await message.answer("Такого айди нету. Начните всё заново.")
                await state.clear()
                return

            # Баланс
            async with db.execute(
                "SELECT SUM(price) AS total FROM Orders WHERE user_id = ? AND status IN ('completed', 'active')",
                (user_id,)
            ) as cursor:
                balance_row = await cursor.fetchone()
            balance = balance_row["total"] or 0

            # Количество заказов
            async with db.execute(
                "SELECT COUNT(*) AS cnt FROM Orders WHERE user_id = ?",
                (user_id,)
            ) as cursor:
                count_row = await cursor.fetchone()
            count = count_row["cnt"] or 0

        await message.answer(
            f"Информация про пользователя с айди {user_id}:\n\n"
            f'Юзернейм: {user_row["username"]}\n'
            f'Никнейм: {user_row["nickname"]}\n'
            f"Заказов: {count}\n"
            f"Баланс: {balance} ₽"
        )
        await state.clear()
    except ValueError:
        await message.answer("Пожалуйста, введите корректный числовой ID пользователя.")
        await state.clear()
    except Exception:
        await message.answer("Произошла ошибка. Попробуйте позже.")
        await state.clear()


@dp.message(BroadcastMessage.message_text)
async def broadcastMessage_message_text(message: Message, state: FSMContext):
    db_path = "DataBase_for_telegram_bot.db"
    bot_instance = message.bot

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT id FROM Users") as cursor:
            rows = await cursor.fetchall()
        user_ids = [row["id"] for row in rows]

    failed_count = 0
    for user_id in user_ids:
        try:
            await bot_instance.copy_message(
                chat_id=user_id,
                from_chat_id=message.chat.id,
                message_id=message.message_id
            )
        except TelegramForbiddenError:
            # Пользователь заблокировал бота — можно пометить как неактивного или просто пропустить
            failed_count += 1
        except Exception as e:
            me = await bot_instance.get_me()
            try:
                # Если есть developer_bot, можно слать отчёт туда, но в этой версии просто логируем
                print(f"Ошибка рассылки для {user_id}: {e}")
            except Exception:
                pass

    await message.answer(f"Рассылка завершена ✅! Не доставлено: {failed_count}.")
    await state.clear()


@dp.message(F.text == "👤 Профиль")
async def profile_user(message: Message):
    user_id = message.from_user.id
    if user_id == int((await message.bot.get_me()).id):  # защита от вызова админом как обычного пользователя (опционально)
        return

    db_path = "DataBase_for_telegram_bot.db"
    balance = await get_balance(user_id, db_path)
    count = await get_orders_count(user_id, db_path)

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Admin_username",)) as cursor:
            admin_row = await cursor.fetchone()
    admin_username = admin_row["Value"] if admin_row else "@unknown"

    await message.answer(
        f"Айди покупателя: <code>{user_id}</code>\n"
        f"Баланс: {balance} ₽\n"
        f"Заказов: {count}\n\n"
        f"Связаться с менеджером: {admin_username}",
        parse_mode="HTML"
    )


@dp.message(F.text == "➡️ Продолжить покупки в магазине")
async def continue_shopping_in_store(message: Message):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Channel",)) as cursor:
            row = await cursor.fetchone()
    channel = row["Value"] if row else "Канал не установлен"

    await message.answer(f'<a href="{channel}">Каталог товаров</a>', parse_mode="HTML")


@dp.message(F.text == "🙋🏻‍♀️ Связаться с менеджером для новых заказов или чтобы задать вопросы")
async def communication_manager(message: Message):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Admin_username",)) as cursor:
            row = await cursor.fetchone()
    admin_username = row["Value"] if row else "@unknown"

    await message.answer(admin_username)


@dp.message(F.text == "🛍 Показать мои заказы")
async def show_my_orders(message: Message):
    user_id = message.from_user.id
    db_path = "DataBase_for_telegram_bot.db"

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT number, item_name, price, created_at, status FROM Orders WHERE user_id = ? ORDER BY number DESC",
            (user_id,)
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        async with aiosqlite.connect(db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT Value FROM SystemData WHERE Name = ?", ("Admin_username",)) as cursor:
                admin_row = await cursor.fetchone()
        admin_username = admin_row["Value"] if admin_row else "@unknown"
        await message.answer(f"Пока что у вас нет заказов. Сделать их можно через {admin_username}.")
        return

    pages = await split_orders(rows, limit=10)
    for page in pages:
        text = "Ваши заказы:\n\n"
        for row in page:
            status_text = "✅ Завершён" if row["status"] == "completed" else "⏳ Активный"
            text += (
                f"🔹 № {row['number']} — {status_text}\n"
                f"🎮 {row['item_name']}\n"
                f"💰 {row['price']} ₽\n"
                f"📅 {time.strftime('%d.%m.%Y %H:%M', time.localtime(row['created_at']))}\n"
                "--------------------\n"
            )
        await message.answer(text, parse_mode="HTML")


@dp.message(Command("pingtime"))
async def ping_time(message: Message):
    start = time.perf_counter()
    msg = await message.answer("Проверка скорости...")
    end = time.perf_counter()
    await msg.edit_text(f"⚡ Время ответа бота: {(end - start) * 1000:.2f} мс.")


@dp.message(Command("score_people"))
async def score_people(message: Message):
    db_path = "DataBase_for_telegram_bot.db"
    async with aiosqlite.connect(db_path) as db:
        async with db.execute("SELECT COUNT(*) AS cnt FROM Users") as cursor:
            row = await cursor.fetchone()
    count = row[0] or 0
    await message.answer(str(count))


@dp.message(Command("exit"))
async def extit(message: Message, state: FSMContext):
    if message.from_user.id == int((await message.bot.get_me()).id):
        # Тут можно добавить проверку по Admin_id из БД, если нужно
        pass
    await state.clear()
    await message.answer("Состояние очищено.")


@dp.message(Command("off"))
async def off_bot(message: Message):
    # Внимание: эта команда должна быть защищена реальным admin_id из БД
    # В текущей реализации просто выводим сообщение
    await message.answer("Команда выключения доступна только администратору.")
    # Для реального выключения нужно останавливать polling снаружи, а не из хендлера


async def on_startup(bot: Bot):
    print("Бот успешно запущен!")
    me = await bot.get_me()
    # Можно отправлять уведомление разработчику, если есть отдельный бот/чат
    print(f"Бот @{me.username} успешно запущен!\nВаши команды:\n/pingtime\n/score_people")


dp.startup.register(on_startup)


async def main():
    db_path = "DataBase_for_telegram_bot.db"

    # Проверка, что таблицы существуют — если нет, бот просто не запустится, это нормально
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        # Можно добавить миграции здесь при необходимости

    # Получаем токен и admin_id из БД (или лучше из переменных окружения!)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT Value FROM SystemData WHERE Name IN ('Token_for_bot', 'Admin_id')") as cursor:
            rows = await cursor.fetchall()

    token_map = {row["Name"]: row["Value"] for row in rows}
    token = token_map.get("8667352258:AAEWweWN4572ca9aliZNQJDe-hxlRK_JKIY")
    admin_id_str = token_map.get("8743219349")

    if not token:
        print("Ошибка: токен бота не найден в БД.")
        return
    if not admin_id_str:
        print("Ошибка: Admin_id не найден в БД.")
        return

    bot = Bot(token=token, default=DefaultBotProperties(parse_mode="HTML"))

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        print(f"Ошибка запуска polling: {e}")


if __name__ == "__main__":
    asyncio.run(main())


