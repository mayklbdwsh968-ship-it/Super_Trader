"""
ملف: Loger.py
الوظيفة: نظام تسجيل مركزي مستقل تماماً عن نظام التداول. يعترض دالة
         print() نفسها على مستوى البرنامج كاملاً (builtins.print) —
         أي استدعاء print() من أي ملف في المشروع (Manager.py،
         Entry_Decision_File.py، Exit_Decision_File.py،
         Fetching_Trading_Data_File.py، Decision_Execution_File.py...
         إلخ) يُسجَّل تلقائياً في Log.txt، دون الحاجة لتعديل أي من
         تلك الملفات أو استبدال print() فيها بدالة مخصصة.
المسار: Super_Trader/Loger.py

طريقة الاستخدام:
    يكفي إضافة سطر واحد في أول ملف Manager.py (قبل أي استيراد آخر
    لملفات المشروع، حتى تُسجَّل رسائل الاستيراد نفسها أيضاً):

        import Loger

    بمجرد الاستيراد، يُفعَّل الاعتراض تلقائياً (عبر install() المستدعاة
    في نهاية هذا الملف) — لا حاجة لأي استدعاء إضافي في Manager.py.

ملاحظة Google Colab:
    - إن كان مجلد المشروع بالكامل موجوداً فعلياً داخل Google Drive
      (مثال: '/content/drive/MyDrive/Super_Trader/')، فإن Log.txt الذي
      يُنشئه هذا الملف يكون أصلاً محفوظاً داخل Drive لحظياً مع كل سطر
      يُكتب — لا حاجة لأي نسخة إضافية أو نسخ يدوي عند نهاية الجلسة.
    - أما إن كان المشروع يعمل من قرص Colab المحلي المؤقت
      ('/content/...' خارج Drive) بينما Drive مربوط فقط للاستخدام،
      فعندها Log.txt سيُفقَد بانتهاء الجلسة، وتحتاج عندها نسخة
      Loger_Colab.py (تمتد من هذا الملف وتضيف نسخاً احتياطياً دورياً
      وعند نهاية الجلسة إلى Drive) بدلاً من هذا الملف.
"""

import builtins
import datetime
import os
import sys

# ══════════════════════════════════════════════
#   إعدادات المسار
# ══════════════════════════════════════════════
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "Log.txt")

# الاحتفاظ بمرجع لدالة print() الأصلية قبل استبدالها، لاستخدامها داخلياً
# ولتفادي أي حلقة لا نهائية لو استُورد هذا الملف أكثر من مرة
_original_print = builtins.print
_log_file_handle = None
_installed = False


# ══════════════════════════════════════════════
#   فتح/إعادة فتح ملف السجل عند الحاجة (Append دائماً — لا حذف)
# ══════════════════════════════════════════════
def _get_log_handle():
    global _log_file_handle
    if _log_file_handle is None or _log_file_handle.closed:
        try:
            _log_file_handle = open(LOG_FILE, "a", encoding="utf-8")
        except Exception as e:
            _original_print(f"[Loger] ⚠️ تعذّر فتح {LOG_FILE}: {e}")
            _log_file_handle = None
    return _log_file_handle


# ══════════════════════════════════════════════
#   الدالة البديلة لـ print() — تطبع في الطرفية كالمعتاد + تُسجِّل
# ══════════════════════════════════════════════
def _logging_print(*args, **kwargs):
    # 1) السلوك الأصلي كما هو — الطباعة في الطرفية دون أي تغيير
    _original_print(*args, **kwargs)

    # 2) نفس الرسالة تُكتب في Log.txt مع طابع زمني دقيق
    try:
        sep     = kwargs.get("sep", " ")
        message = sep.join(str(a) for a in args)

        timestamp     = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        clean_message = message.strip("\n")

        # الحفاظ على الأسطر الفارغة/الفواصل الشكلية (مثل "-"*60) كما هي
        # في الملف أيضاً، لتطابق السجل مع ما يظهر في الطرفية تماماً
        handle = _get_log_handle()
        if handle is not None:
            handle.write(f"[{timestamp}] {clean_message}\n")
            handle.flush()
    except Exception as e:
        # أي فشل في التسجيل لا يجب أن يوقف تشغيل البوت إطلاقاً
        _original_print(f"[Loger] ⚠️ فشل الكتابة في Log.txt: {e}")


# ══════════════════════════════════════════════
#   تفعيل الاعتراض (يُستدعى تلقائياً عند استيراد الملف)
# ══════════════════════════════════════════════
def install():
    global _installed
    if _installed:
        return
    builtins.print = _logging_print
    _installed = True
    _original_print(
        f"[Loger] ✅ تم تفعيل نظام التسجيل المركزي — كل print() من كل "
        f"ملفات المشروع سيُسجَّل تلقائياً في: {LOG_FILE}"
    )


# ══════════════════════════════════════════════
#   إغلاق آمن للملف — يُستدعى عند إيقاف يدوي أو نهاية طبيعية للبرنامج
# ══════════════════════════════════════════════
def flush_and_close():
    global _log_file_handle
    if _log_file_handle is not None and not _log_file_handle.closed:
        try:
            _log_file_handle.flush()
            _log_file_handle.close()
        except Exception:
            pass


# تفعيل تلقائي فور الاستيراد — لا حاجة لاستدعاء install() يدوياً من Manager.py
install()

# إغلاق آمن للملف عند خروج طبيعي من البرنامج (لا يضمن التنفيذ عند
# قتل العملية بالقوة — لهذا توجد نسخة Loger_Colab.py بنسخ احتياطي دوري)
import atexit
atexit.register(flush_and_close)
