# دفتر گردش اسناد مهندسی — گالری دوزبانه تصاویر واقعی اکسل | V02

## نصب

فایل ZIP را در پوشهٔ اصلی پروژهٔ `cleaner-functions` استخراج کنید. نسخهٔ قبلی (`GENERAL_DOC_REAL_SCREENSHOT_GALLERY.py`) **تغییر نمی‌کند**.

این نسخه از واژگان مصوب استفاده می‌کند: «دفتر گردش اسناد مهندسی»، «بخش مهندسی»، «سند/اسناد»، «نسخه (Revision)»، «فایل اکسل اصلی»، «نظافتچی»، «نظافت»، «فایل اکسل در حال نظافت»، «مغایرت»، «سبد پروژه‌ها»، «شواهد اصلی»، «رسیدگی‌نشده»، «در انتظار رسیدگی»، «شرح رویداد». در ساختار اکسل «سلول مرکب» و در محتوای چندگانه «ترکیبی» استفاده می‌شود.

### ۱. آزمون سریع بدون اجرای اکسل

```bat
py -m unittest -q test_general_doc_gallery_v02.py test_general_doc_gallery_compat_v02.py
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02.py --mode inventory --no-pdf --lang both
```

### ۲. تصویربرداری واقعی اکسل، ابتدا یک پروژه

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02.py --projects YSK --lang both --pdf
```

### ۳. گالری کل سبد (هر هشت پروژه)

```bat
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02.py --lang both --pdf
```

- `--lang both`: خروجی مستقل فارسی RTL و انگلیسی LTR (پیش‌فرض).
- `--lang fa`: فقط فارسی.
- `--lang en`: فقط انگلیسی.
- `--no-pdf`: تولید HTML و CSV بدون چاپ PDF.
- `--mode inventory`: ایجاد گزارش آزمایشی بدون Excel COM یا تصاویر واقعی.
- `--projects AZD,JND`: محدودکردن به پروژه‌های معین.

## خروجی‌ها

در `portfolio_audits\general_doc_real_excel_gallery_YYYYMMDDTHHMMSS`:

| خروجی | توضیح |
|---|---|
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_FA.html` | گالری فارسی راست‌به‌چپ با عناوین قواعد و اقدامات فارسی |
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_EN.html` | گالری انگلیسی چپ‌به‌راست |
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY.html` | مسیر پیش‌فرض برای بازکردن گالری (فارسی، در حالت both) |
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_FA.pdf` | PDF فارسی در صورت موفقیت چاپ مرورگر |
| `GENERAL_DOCUMENT_REAL_EXCEL_GALLERY_EN.pdf` | PDF انگلیسی در صورت موفقیت چاپ مرورگر |
| `all_103_findings_bilingual.csv` | تمامی ۱۰۳ مغایرت همراه با عناوین و اقدامات فارسی |
| `all_58_grouped_cases_bilingual.csv` | ۵۸ گروه رسیدگی دوزبانه |
| `BILINGUAL_TERMS.csv` | واژه‌نامهٔ مصوب، برچسب‌های رابط، وضعیت‌ها و ۲۱ قاعده |
| `images\original`, `images\cleaned` | تصاویر واقعی محدوده‌های اکسل (در حالت capture) |
| `approved_overlay_outcomes.csv`, `capture_warnings.csv` | نتایج اعمال اصلاحات و خطاهای تصویربرداری |

**توجه:** صرف وجود تصویر فایل در حال نظافت، به معنی رفع مغایرت نیست. حالت `APPROVED_OVERLAY_RENDERED` تنها نمایش اصلاح سلولی تأییدشده در نسخهٔ موقت است؛ تأیید تجاری یا اصلاح کل سند محسوب نمی‌شود. هر مورد دیگر «رسیدگی‌نشده» می‌ماند. کدهای WBS، شناسه‌ها، شماره‌های نامه، متن شواهد و آدرس سلول‌ها عیناً حفظ می‌شوند.

تصاویر با Microsoft Excel (`Range.CopyPicture`) گرفته می‌شوند. نسخهٔ در حال نظافت، کپی موقت بوده و تغییرات `resolved_state.json` با کنترل مقدار قبلی روی آن اعمال می‌شود؛ فایل اصلی و فایل کاری نظافتچی ذخیره یا ویرایش نمی‌شوند. نیاز به Tesseract نیست. برای گرفتن تصاویر باید Windows، Microsoft Excel و `pywin32` موجود باشد؛ برای PDF مرورگر Edge یا Chrome لازم است. در صورت خطای چاپ خودکار، فایل HTML را در Edge باز کنید، `Ctrl+P` بزنید و `Save as PDF` را انتخاب کنید.

**حدود آزمون این بسته:** ۱۹ آزمون بدون نیاز به Excel COM در محیط توسعه موفق بودند. تصویربرداری واقعی و چاپ PDF دوزبانه در محیط ویندوز شما هنوز باید اجرا و تأیید شوند.

---

# General Document native Excel bilingual gallery — V02

Unzip this package directly into the existing `cleaner-functions` repository root. It **does not overwrite V01**. Generate Persian RTL and English LTR galleries from the same 58 review assignments and 103 traceable findings.

```bat
py -m unittest -q test_general_doc_gallery_v02.py test_general_doc_gallery_compat_v02.py
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02.py --projects YSK --lang both --pdf
py .\GENERAL_DOC_REAL_SCREENSHOT_GALLERY_V02.py --lang both --pdf
```

The Persian report translates the rule title and corrective instruction but **preserves original source evidence**, including the original English scanner explanation, in an identified field. `MERGED_STATUS` means a status in a **merged Excel cell** (سلول مرکب), not automatically a combined/ambiguous business status (وضعیت ترکیبی).

The output shows genuine before/working Excel screenshots, never generated "fixed" pictures. An approved run-local correction is rendered only in a disposable copy with expected-value safeguards. Unresolved cases stay open. Both language PDFs depend on Edge/Chrome printing on the user's machine; `--mode inventory --no-pdf` can be run without Excel.
