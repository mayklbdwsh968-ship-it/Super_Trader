code = """#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسم الملف: main.py
وظيفة الملف: استقبال وإرسال رسائل بوت Telegram وتنفيذ عمليات التحكم بـ Super_Trader
المسار: Super_Trader/main.py
"""

import os
import re
import sys
import signal
import subprocess
import logging
from threading import Thread
from flask import Flask

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ══════════════════════════════════════════════
#   الإعدادات الثابتة
# ══════════════════════════════════════════════
BOT_TOKEN          = "8400206350:AAEnl9Q2ZxAfDFF52-fbGt1gxpsFVEDwFHE"
AUTHORIZED_USER_ID = 7871552897

BASE_DIR          = os.path.dirname(os.path.abspath(__file__))
LOG_FILE          = os.path.join(BASE_DIR, "Log.txt")
SETTINGS_FILE     = os.path.join(BASE_DIR, "Settings.py")
MANAGER_FILE      = os.path.join(BASE_DIR, "Manager.py")
MANAGER_PID_FILE  = os.path.join(BASE_DIR, "manager.pid")

TELEGRAM_MAX_MESSAGE_LENGTH = 4096

WELCOME_MESSAGE = (
    "مرحبا بك في Super_Trader، للتحكم بالروبوت استخدم الأوامر التالية:\n\n"
    "/Start_bot\n"
    "لتشغيل روبوت التداول\n\n"
    "/Stop_bot\n"
    "لإيقاف روبوت التداول\n\n"
    "/See_log\n"
    "لإرسال محتوى ملف Log.txt\n\n"
    "/Delete_log\n"
    "لحذف ملف Log.txt الحالي\n\n"
    "/Change_Symbol\n"
    "لتغير زوج التداول\n\n"
    "/Change_Access_Key\n"
    "لتغير مفتاح MEXC Access Key\n\n"
    "/Change_Secret_Key\n"
    "لتغير مفتاح MEXC Secret Key\n\n"
    "/Change_Buy_Volume\n"
    "لتغير نسبة رأس المال المستخدمة في الشراء\n\n"
    "/See_Settings\n"
    "لرؤية الاعدادات الحالية"
)

UNAUTHORIZED_MESSAGE = "❌ غير مصرح لك باستخدام هذا البوت"

_STRING_SETTINGS  = {"Symbol", "Access_Key", "Secret_Key"}
_NUMERIC_SETTINGS = {"Buy_Volume"}

# ══════════════════════════════════════════════
#   الحالة أثناء التشغيل (State)
# ══════════════════════════════════════════════
manager_process         = None   # subprocess.Popen أو None
pending_setting_change  = None   # None أو اسم المتغير المطلوب تعديله

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("Super_Trader_Bot")


# ══════════════════════════════════════════════
#   خادم ويب وهمي (Flask) لأجل الاستضافة والحماية من النوم
#   يعمل بالتوازي في خلفية الكود ليتناسب مع أي خادم سحابي
# ══════════════════════════════════════════════
app = Flask('')

# إيقاف طباعة سجلات طلبات Flask الافتراضية المزعجة في الطرفية ليبقى الـ Log نظيفاً
flask_log = logging.getLogger('wsgi')
flask_log.setLevel(logging.ERROR)

@app.route('/')
def home():
    return "البوت يعمل بنجاح 24/7!"


def _run_web_server():
    # استخدام المنفذ الممرر عبر متغيرات البيئة تلقائياً ليتناسب مع Koyeb, Render, Heroku وغيرها
    port = int(os.environ.get("PORT", 8080))
    try:
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.warning(f"⚠️ تعذّر تشغيل خادم ويب Flask: {e}")


def _keep_alive():
    # تشغيل خادم الويب في خلفية الكود لحماية البوت من النوم
    t = Thread(target=_run_web_server, daemon=True)
    t.start()


# ══════════════════════════════════════════════
#   دوال مساعدة: التحقق من الصلاحية
# ══════════════════════════════════════════════
def _is_authorized(update: Update) -> bool:
    return update.effective_user is not None and update.effective_user.id == AUTHORIZED_USER_ID


async def _reject_unauthorized(update: Update):
    await update.message.reply_text(UNAUTHORIZED_MESSAGE)


# ══════════════════════════════════════════════
#   دوال مساعدة: إدارة عملية Manager.py
# ══════════════════════════════════════════════
def _read_saved_pid():
    if not os.path.exists(MANAGER_PID_FILE):
        return None
    try:
        with open(MANAGER_PID_FILE, "r") as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _is_manager_running() -> bool:
    global manager_process
    if manager_process is not None and manager_process.poll() is None:
        return True
    pid = _read_saved_pid()
    if pid is not None and _pid_alive(pid):
        return True
    return False


def _get_manager_pid():
    global manager_process
    if manager_process is not None and manager_process.poll() is None:
        return manager_process.pid
    return _read_saved_pid()


# ══════════════════════════════════════════════
#   دالة مساعدة: تعديل متغير داخل Settings.py
# ══════════════════════════════════════════════
def _update_setting_in_file(setting_name: str, new_value: str):
    if not os.path.exists(SETTINGS_FILE):
        raise FileNotFoundError("ملف Settings.py غير موجود.")

    with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    if setting_name in _NUMERIC_SETTINGS:
        normalized = new_value.strip().replace(",", ".")
        try:
            float(normalized)
        except ValueError:
            raise ValueError("القيمة المدخلة يجب أن تكون رقماً عشرياً صحيحاً (مثال: 0.25)")
        replacement = f"{setting_name} = {normalized}"
    else:
        escaped_value = new_value.strip().replace('"', '\\"')
        replacement = f'{setting_name} = "{escaped_value}"'

    pattern = rf"^{re.escape(setting_name)}\s*=\s*.+$"
    new_content, count = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)

    if count == 0:
        raise ValueError(f"لم يتم العثور على المتغير {setting_name} داخل ملف Settings.py")

    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        f.write(new_content)


# ══════════════════════════════════════════════
#   أوامر البوت
# ══════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    await update.message.reply_text(WELCOME_MESSAGE)


async def cmd_start_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manager_process

    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if not os.path.exists(MANAGER_FILE):
        await update.message.reply_text("❌ ملف Manager.py غير موجود في مجلد المشروع.")
        return

    if _is_manager_running():
        await update.message.reply_text("⚠️ روبوت التداول يعمل بالفعل.")
        return

    try:
        manager_process = subprocess.Popen(
            [sys.executable, MANAGER_FILE],
            cwd=BASE_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with open(MANAGER_PID_FILE, "w") as f:
            f.write(str(manager_process.pid))

        await update.message.reply_text("✅ تم تشغيل روبوت التداول.")
        logger.info(f"تم تشغيل Manager.py بمعرف العملية {manager_process.pid}")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل تشغيل روبوت التداول:\n{e}")
        logger.error(f"فشل تشغيل Manager.py: {e}")


async def cmd_stop_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global manager_process

    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if not _is_manager_running():
        await update.message.reply_text("⚠️ روبوت التداول متوقف بالفعل.")
        return

    pid = _get_manager_pid()

    try:
        os.kill(pid, signal.SIGTERM)

        if manager_process is not None and manager_process.poll() is None:
            try:
                manager_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.kill(pid, signal.SIGKILL)
        else:
            import time
            time.sleep(3)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)

        manager_process = None
        if os.path.exists(MANAGER_PID_FILE):
            os.remove(MANAGER_PID_FILE)

        await update.message.reply_text("🛑 تم إيقاف روبوت التداول.")
        logger.info(f"تم إيقاف Manager.py (PID={pid})")

    except ProcessLookupError:
        manager_process = None
        if os.path.exists(MANAGER_PID_FILE):
            os.remove(MANAGER_PID_FILE)
        await update.message.reply_text("⚠️ العملية غير موجودة أصلاً — تم تنظيف الحالة.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل إيقاف روبوت التداول:\n{e}")
        logger.error(f"فشل إيقاف Manager.py: {e}")


async def cmd_see_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("⚠️ ملف Log.txt غير موجود حالياً.")
        return

    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        await update.message.reply_text(f"❌ فشل قراءة ملف Log.txt:\n{e}")
        return

    if not content.strip():
        await update.message.reply_text("⚠️ ملف Log.txt فارغ.")
        return

    if len(content) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        await update.message.reply_text(content)
    else:
        try:
            with open(LOG_FILE, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="Log.txt",
                    caption=(
                        "📄 محتوى Log.txt (تم إرساله كملف مرفق لأن حجمه "
                        "تجاوز الحد المسموح لرسائل تيلجرام)."
                    ),
                )
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال ملف Log.txt:\n{e}")


async def cmd_delete_log(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("⚠️ ملف Log.txt غير موجود أصلاً.")
        return

    try:
        os.remove(LOG_FILE)
        await update.message.reply_text("🗑️ تم حذف ملف Log.txt.")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل حذف ملف Log.txt:\n{e}")


async def cmd_see_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if not os.path.exists(SETTINGS_FILE):
        await update.message.reply_text("⚠️ ملف Settings.py غير موجود حالياً.")
        return

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception as e:
        await update.message.reply_text(f"❌ فشل قراءة ملف Settings.py:\n{e}")
        return

    if not content.strip():
        await update.message.reply_text("⚠️ ملف Settings.py فارغ.")
        return

    if len(content) <= TELEGRAM_MAX_MESSAGE_LENGTH:
        await update.message.reply_text(content)
    else:
        try:
            with open(SETTINGS_FILE, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="Settings.py",
                    caption=(
                        "📄 محتوى Settings.py (تم إرساله كملف مرفق لأن حجمه "
                        "تجاوز الحد المسموح لرسائل تيلجرام)."
                    ),
                )
        except Exception as e:
            await update.message.reply_text(f"❌ فشل إرسال ملف Settings.py:\n{e}")


async def cmd_change_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_setting_change
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    pending_setting_change = "Symbol"
    await update.message.reply_text("اكتب اسم زوج التداول الجديد")


async def cmd_change_access_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_setting_change
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    pending_setting_change = "Access_Key"
    await update.message.reply_text("اكتب مفتاح MEXC Access Key الجديد")


async def cmd_change_secret_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_setting_change
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    pending_setting_change = "Secret_Key"
    await update.message.reply_text("اكتب مفتاح MEXC Secret Key الجديد")


async def cmd_change_buy_volume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_setting_change
    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return
    pending_setting_change = "Buy_Volume"
    await update.message.reply_text("اكتب نسبة رأس المال المستخدمة في الشراء بشكل عشري")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_setting_change

    if not _is_authorized(update):
        await _reject_unauthorized(update)
        return

    if pending_setting_change is None:
        return  # لا يوجد تعديل بانتظار التنفيذ حالياً — تجاهل الرسالة

    new_value    = update.message.text.strip()
    setting_name = pending_setting_change
    pending_setting_change = None  # نصفّر الحالة فوراً لمنع أي تعديل مزدوج بالخطأ

    try:
        _update_setting_in_file(setting_name, new_value)
        await update.message.reply_text(f"✅ تم تحديث {setting_name} بنجاح إلى:\n{new_value}")
        logger.info(f"تم تحديث {setting_name} في Settings.py")
    except Exception as e:
        await update.message.reply_text(f"❌ فشل تحديث {setting_name}:\n{e}")
        logger.error(f"فشل تحديث {setting_name}: {e}")


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"حدث خطأ غير متوقع: {context.error}")


# ══════════════════════════════════════════════
#   نقطة الدخول
# ══════════════════════════════════════════════
def main():
    if not BOT_TOKEN or ":" not in BOT_TOKEN:
        logger.critical("❌ توكن البوت غير صالح.")
        sys.exit(1)

    # تشغيل خادم ويب Flask في الخلفية لحماية البوت من النوم متوافقاً مع أي خادم سحابي
    _keep_alive()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("Start_bot", cmd_start_bot))
    application.add_handler(CommandHandler("Stop_bot", cmd_stop_bot))
    application.add_handler(CommandHandler("See_log", cmd_see_log))
    application.add_handler(CommandHandler("Delete_log", cmd_delete_log))
    application.add_handler(CommandHandler("Change_Symbol", cmd_change_symbol))
    application.add_handler(CommandHandler("Change_Access_Key", cmd_change_access_key))
    application.add_handler(CommandHandler("Change_Secret_Key", cmd_change_secret_key))
    application.add_handler(CommandHandler("Change_Buy_Volume", cmd_change_buy_volume))
    application.add_handler(CommandHandler("See_Settings", cmd_see_settings))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    application.add_error_handler(_on_error)

    logger.info("🚀 بدء تشغيل بوت Super_Trader ...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
"""

with open("main.py", "w", encoding="utf-8") as f:
    f.write(code)
print("File generated successfully")
