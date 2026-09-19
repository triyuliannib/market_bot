import os
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

OWNER_1 = "Yul"
OWNER_2 = "Sam"

DB_FILE = "luggage_market.db"


# ============================================================
# DATABASE
# ============================================================

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            owner1_items INTEGER NOT NULL,
            owner2_items INTEGER NOT NULL,
            total_items INTEGER NOT NULL,
            normal_price_cents INTEGER NOT NULL,
            actual_price_cents INTEGER NOT NULL,
            owner1_share_cents INTEGER NOT NULL,
            owner2_share_cents INTEGER NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_sale(
    owner1_items,
    owner2_items,
    normal_price_cents,
    actual_price_cents,
    owner1_share_cents,
    owner2_share_cents,
):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sales (
            created_at,
            owner1_items,
            owner2_items,
            total_items,
            normal_price_cents,
            actual_price_cents,
            owner1_share_cents,
            owner2_share_cents
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().isoformat(),
        owner1_items,
        owner2_items,
        owner1_items + owner2_items,
        normal_price_cents,
        actual_price_cents,
        owner1_share_cents,
        owner2_share_cents,
    ))

    sale_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return sale_id


# ============================================================
# PRICING
# ============================================================

def calculate_bundle_price(item_count):
    """
    Bundle price:
    1 item = $5
    2 items = $8
    3 items = $10

    4 items = $15
    5 items = $18
    6 items = $20
    etc.
    """

    if item_count <= 0:
        return 0

    groups_of_3 = item_count // 3
    remainder = item_count % 3

    total = groups_of_3 * 1000

    if remainder == 1:
        total += 500

    elif remainder == 2:
        total += 800

    return total


def split_price(
    total_cents,
    owner1_items,
    owner2_items
):
    """
    Split sale amount based on number of items.
    """

    total_items = (
        owner1_items
        + owner2_items
    )

    if total_items == 0:
        return 0, 0

    owner1_ratio = (
        Decimal(owner1_items)
        / Decimal(total_items)
    )

    owner1_share = (
        Decimal(total_cents)
        * owner1_ratio
    ).quantize(
        Decimal("1"),
        rounding=ROUND_HALF_UP
    )

    owner1_share = int(owner1_share)

    owner2_share = (
        total_cents
        - owner1_share
    )

    return owner1_share, owner2_share


def money(cents):
    return f"${cents / 100:.2f}"


# ============================================================
# BASKET
# ============================================================

def get_basket(context):
    if "basket" not in context.application.bot_data:
        context.application.bot_data["basket"] = {
            "owner1": 0,
            "owner2": 0,
            "current_price": 0,
            "price_modified": False,
        }

    return context.application.bot_data["basket"]


def reset_basket(context):
    context.application.bot_data["basket"] = {
        "owner1": 0,
        "owner2": 0,
        "current_price": 0,
        "price_modified": False,
    }

    context.application.bot_data["awaiting_custom_price"] = False


def recalculate_price(basket):
    """
    Reset current price to bundle price
    whenever items change.
    """

    total_items = (
        basket["owner1"]
        + basket["owner2"]
    )

    basket["current_price"] = (
        calculate_bundle_price(
            total_items
        )
    )

    basket["price_modified"] = False


# ============================================================
# CASHIER SCREEN
# ============================================================

def basket_text(basket):
    owner1 = basket["owner1"]
    owner2 = basket["owner2"]

    total_items = owner1 + owner2

    normal_price = (
        calculate_bundle_price(
            total_items
        )
    )

    current_price = (
        basket["current_price"]
    )

    text = (
        "🧳 TORTURED CLOSETS\n\n"
        f"{OWNER_1}: {owner1}\n"
        f"{OWNER_2}: {owner2}\n\n"
        f"Items: {total_items}\n\n"
    )

    if basket["price_modified"]:

        text += (
            f"Bundle Price: "
            f"{money(normal_price)}\n"
            f"Current Price: "
            f"{money(current_price)}"
        )

    else:

        text += (
            f"Current Price: "
            f"{money(current_price)}"
        )

    return text


def basket_keyboard(basket):
    current_price = (
        basket["current_price"]
    )

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"➕ {OWNER_1}",
                callback_data="add_owner1"
            ),
            InlineKeyboardButton(
                f"➕ {OWNER_2}",
                callback_data="add_owner2"
            ),
        ],

        [
            InlineKeyboardButton(
                f"➖ {OWNER_1}",
                callback_data="remove_owner1"
            ),
            InlineKeyboardButton(
                f"➖ {OWNER_2}",
                callback_data="remove_owner2"
            ),
        ],

        [
            InlineKeyboardButton(
                "-$1",
                callback_data="minus_100"
            ),
            InlineKeyboardButton(
                "+$1",
                callback_data="plus_100"
            ),
        ],

        [
            InlineKeyboardButton(
                "✏️ Custom Price",
                callback_data="custom_price"
            ),
        ],

        [
            InlineKeyboardButton(
                "🗑 Clear",
                callback_data="clear"
            ),
        ],

        [
            InlineKeyboardButton(
                f"💰 CHECKOUT "
                f"{money(current_price)}",
                callback_data="checkout"
            ),
        ],
    ])


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    basket = get_basket(context)

    await update.message.reply_text(
        basket_text(basket),
        reply_markup=basket_keyboard(
            basket
        )
    )


# ============================================================
# NEW SALE
# ============================================================

async def new_sale(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    reset_basket(context)

    basket = get_basket(context)

    await update.message.reply_text(
        basket_text(basket),
        reply_markup=basket_keyboard(
            basket
        )
    )


# ============================================================
# CLEAR COMMAND
# ============================================================

async def clear_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    reset_basket(context)

    basket = get_basket(context)

    await update.message.reply_text(
        "🗑 Basket cleared.\n\n"
        + basket_text(basket),
        reply_markup=basket_keyboard(
            basket
        )
    )


# ============================================================
# BUTTON HANDLER
# ============================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query

    await query.answer()

    basket = get_basket(context)


    # --------------------------------------------------------
    # ADD YUL
    # --------------------------------------------------------

    if query.data == "add_owner1":

        basket["owner1"] += 1

        recalculate_price(basket)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # ADD SAM
    # --------------------------------------------------------

    elif query.data == "add_owner2":

        basket["owner2"] += 1

        recalculate_price(basket)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # REMOVE YUL
    # --------------------------------------------------------

    elif query.data == "remove_owner1":

        if basket["owner1"] > 0:

            basket["owner1"] -= 1

        recalculate_price(basket)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # REMOVE SAM
    # --------------------------------------------------------

    elif query.data == "remove_owner2":

        if basket["owner2"] > 0:

            basket["owner2"] -= 1

        recalculate_price(basket)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # - $1
    # --------------------------------------------------------

    elif query.data == "minus_100":

        if basket["current_price"] >= 100:

            basket["current_price"] -= 100

        else:

            basket["current_price"] = 0

        basket["price_modified"] = True

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # + $1
    # --------------------------------------------------------

    elif query.data == "plus_100":

        basket["current_price"] += 100

        basket["price_modified"] = True

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )

    # --------------------------------------------------------
    # CUSTOM PRICE
    # --------------------------------------------------------

    elif query.data == "custom_price":

        total_items = (
            basket["owner1"]
            + basket["owner2"]
        )

        if total_items == 0:

            await query.answer(
                "Add an item first.",
                show_alert=True
            )

            return

        context.application.bot_data[
            "awaiting_custom_price"
        ] = True

        await query.message.reply_text(
            "✏️ Enter custom price.\n\n"
            "Example: 7.50"
        )


    # --------------------------------------------------------
    # CLEAR BUTTON
    # --------------------------------------------------------

    elif query.data == "clear":

        reset_basket(context)

        basket = get_basket(context)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # CHECKOUT
    # --------------------------------------------------------

    elif query.data == "checkout":

        total_items = (
            basket["owner1"]
            + basket["owner2"]
        )

        if total_items == 0:

            await query.answer(
                "Add at least one item.",
                show_alert=True
            )

            return

        if basket["current_price"] <= 0:

            await query.answer(
                "Sale price must be "
                "more than $0.",
                show_alert=True
            )

            return

        await complete_sale(
            query,
            context,
            basket["current_price"]
        )


    # --------------------------------------------------------
    # NEW SALE BUTTON
    # --------------------------------------------------------

    elif query.data == "new_sale":

        reset_basket(context)

        basket = get_basket(context)

        await query.edit_message_text(
            basket_text(basket),
            reply_markup=basket_keyboard(
                basket
            )
        )


    # --------------------------------------------------------
    # SELECT SALE TO DELETE
    # --------------------------------------------------------

    elif query.data.startswith(
        "delete_sale_"
    ):

        sale_id = int(
            query.data.replace(
                "delete_sale_",
                ""
            )
        )

        conn = sqlite3.connect(
            DB_FILE
        )

        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                owner1_items,
                owner2_items,
                actual_price_cents
            FROM sales
            WHERE id = ?
        """, (
            sale_id,
        ))

        sale = cursor.fetchone()

        conn.close()

        if not sale:

            await query.edit_message_text(
                "Sale not found."
            )

            return

        (
            owner1_items,
            owner2_items,
            total
        ) = sale

        keyboard = (
            InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Yes, Delete",
                        callback_data=(
                            f"confirm_delete_"
                            f"{sale_id}"
                        )
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel",
                        callback_data=(
                            "cancel_delete"
                        )
                    )
                ]
            ])
        )

        await query.edit_message_text(
            f"⚠️ Delete Sale "
            f"#{sale_id}?\n\n"

            f"{OWNER_1}: "
            f"{owner1_items}\n"

            f"{OWNER_2}: "
            f"{owner2_items}\n\n"

            f"Total: "
            f"{money(total)}",

            reply_markup=keyboard
        )


    # --------------------------------------------------------
    # CONFIRM DELETE
    # --------------------------------------------------------

    elif query.data.startswith(
        "confirm_delete_"
    ):

        sale_id = int(
            query.data.replace(
                "confirm_delete_",
                ""
            )
        )

        conn = sqlite3.connect(
            DB_FILE
        )

        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM sales
            WHERE id = ?
            """,
            (
                sale_id,
            )
        )

        deleted = cursor.rowcount

        conn.commit()
        conn.close()

        if deleted:

            await query.edit_message_text(
                f"✅ Sale #{sale_id} "
                f"deleted."
            )

        else:

            await query.edit_message_text(
                "Sale not found."
            )


    # --------------------------------------------------------
    # CANCEL DELETE
    # --------------------------------------------------------

    elif query.data == "cancel_delete":

        await query.edit_message_text(
            "Delete cancelled."
        )


# ============================================================
# CUSTOM PRICE INPUT
# ============================================================

async def custom_price_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    if not context.application.bot_data.get(
        "awaiting_custom_price"
    ):
        return

    basket = get_basket(context)

    text = (
        update.message.text
        .strip()
        .replace("$", "")
        .replace(",", "")
    )

    try:

        price = Decimal(text)

        if price <= 0:
            raise ValueError

    except Exception:

        await update.message.reply_text(
            "Please enter a valid price.\n"
            "Example: 7.50"
        )

        return

    price_cents = int(
        (
            price * 100
        ).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP
        )
    )

    basket["current_price"] = (
        price_cents
    )

    basket["price_modified"] = True

    context.application.bot_data[
        "awaiting_custom_price"
    ] = False

    await update.message.reply_text(
        basket_text(basket),
        reply_markup=basket_keyboard(
            basket
        )
    )


# ============================================================
# COMPLETE SALE
# ============================================================

async def complete_sale(
    query,
    context,
    total_price
):
    basket = get_basket(context)

    owner1_items = (
        basket["owner1"]
    )

    owner2_items = (
        basket["owner2"]
    )

    total_items = (
        owner1_items
        + owner2_items
    )

    normal_price = (
        calculate_bundle_price(
            total_items
        )
    )

    (
        owner1_share,
        owner2_share
    ) = split_price(
        total_price,
        owner1_items,
        owner2_items
    )

    sale_id = save_sale(
        owner1_items,
        owner2_items,
        normal_price,
        total_price,
        owner1_share,
        owner2_share,
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "➕ NEW SALE",
                callback_data="new_sale"
            )
        ]
    ])

    await query.edit_message_text(
        f"✅ SALE #{sale_id} SAVED\n\n"

        f"Items: {total_items}\n"
        f"Total: {money(total_price)}\n\n"

        f"{OWNER_1}: "
        f"{owner1_items} item(s)\n"
        f"Earnings: "
        f"{money(owner1_share)}\n\n"

        f"{OWNER_2}: "
        f"{owner2_items} item(s)\n"
        f"Earnings: "
        f"{money(owner2_share)}",

        reply_markup=keyboard
    )

    reset_basket(context)


# ============================================================
# SUMMARY
# ============================================================

async def summary(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*),
            COALESCE(
                SUM(total_items),
                0
            ),
            COALESCE(
                SUM(actual_price_cents),
                0
            ),
            COALESCE(
                SUM(owner1_share_cents),
                0
            ),
            COALESCE(
                SUM(owner2_share_cents),
                0
            ),
            COALESCE(
                SUM(owner1_items),
                0
            ),
            COALESCE(
                SUM(owner2_items),
                0
            )
        FROM sales
    """)

    result = cursor.fetchone()

    conn.close()

    (
        sale_count,
        total_items,
        total_sales,
        owner1_total,
        owner2_total,
        owner1_items,
        owner2_items,
    ) = result

    await update.message.reply_text(
        "📊 SALES SUMMARY\n\n"

        f"Transactions: "
        f"{sale_count}\n"

        f"Items sold: "
        f"{total_items}\n\n"

        f"💰 Total Sales: "
        f"{money(total_sales)}\n\n"

        f"{OWNER_1}\n"
        f"Items: "
        f"{owner1_items}\n"
        f"Earnings: "
        f"{money(owner1_total)}\n\n"

        f"{OWNER_2}\n"
        f"Items: "
        f"{owner2_items}\n"
        f"Earnings: "
        f"{money(owner2_total)}"
    )


# ============================================================
# RECENT SALES
# ============================================================

async def sales(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            owner1_items,
            owner2_items,
            actual_price_cents,
            owner1_share_cents,
            owner2_share_cents
        FROM sales
        ORDER BY id DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "No sales recorded yet."
        )

        return

    text = "🧾 RECENT SALES\n\n"

    for row in rows:

        (
            sale_id,
            owner1_items,
            owner2_items,
            total,
            owner1_share,
            owner2_share,
        ) = row

        text += (
            f"#{sale_id} • "
            f"{money(total)}\n"

            f"{OWNER_1}: "
            f"{owner1_items} "
            f"→ {money(owner1_share)}\n"

            f"{OWNER_2}: "
            f"{owner2_items} "
            f"→ {money(owner2_share)}\n\n"
        )

    await update.message.reply_text(
        text
    )


# ============================================================
# DELETE SALE COMMAND
# ============================================================

async def delete_sale_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    conn = sqlite3.connect(DB_FILE)

    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            id,
            owner1_items,
            owner2_items,
            actual_price_cents
        FROM sales
        ORDER BY id DESC
        LIMIT 10
    """)

    rows = cursor.fetchall()

    conn.close()

    if not rows:

        await update.message.reply_text(
            "No sales available "
            "to delete."
        )

        return

    keyboard = []

    for (
        sale_id,
        owner1_items,
        owner2_items,
        total
    ) in rows:

        label = (
            f"🗑 #{sale_id} • "
            f"{money(total)} • "
            f"Y:{owner1_items} "
            f"S:{owner2_items}"
        )

        keyboard.append([
            InlineKeyboardButton(
                label,
                callback_data=(
                    f"delete_sale_"
                    f"{sale_id}"
                )
            )
        ])

    await update.message.reply_text(
        "🗑 Choose a sale "
        "to delete:",
        reply_markup=(
            InlineKeyboardMarkup(
                keyboard
            )
        )
    )


# ============================================================
# HELP
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    await update.message.reply_text(
        "📖 AVAILABLE COMMANDS\n\n"

        "/start - Open the cashier\n"
        "/sale - Start a new sale\n"
        "/summary - View sales summary\n"
        "/sales - View recent sales\n"
        "/delete - Delete a selected sale\n"
        "/clear - Clear current basket\n"
        "/help - Show available commands"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN "
            "is not set."
        )

    init_db()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        CommandHandler(
            "sale",
            new_sale
        )
    )

    app.add_handler(
        CommandHandler(
            "summary",
            summary
        )
    )

    app.add_handler(
        CommandHandler(
            "sales",
            sales
        )
    )

    app.add_handler(
        CommandHandler(
            "delete",
            delete_sale_command
        )
    )

    app.add_handler(
        CommandHandler(
            "clear",
            clear_command
        )
    )

    app.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            custom_price_handler
        )
    )

    print(
        "Tortured Closets Bot "
        "is running..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()