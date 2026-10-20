# -*- coding: utf-8 -*-
"""User-approved Persian terminology and bilingual rule descriptions for General Document.

Machine identifiers (rule codes, WBS, paths, file references, dates) are never translated.
The source finding evidence and original Excel content are never altered.
"""
from __future__ import annotations

TERMS = [
    ('General Document','دفتر گردش اسناد مهندسی'),
    ('Engineering','بخش مهندسی'),
    ('Document','سند'),
    ('Documents','اسناد'),
    ('Document Control','کنترل اسناد'),
    ('Document Name','نام سند'),
    ('Document Family','خانوادهٔ اسناد'),
    ('Revision','نسخه (Revision)'),
    ('Original Workbook','فایل اکسل اصلی'),
    ('Cleaner','نظافتچی'),
    ('Clean / Cleaning','نظافت'),
    ('Cleaner Working Workbook','فایل اکسل در حال نظافت'),
    ('Issue','مغایرت'),
    ('Issue Type','نوع مغایرت'),
    ('Portfolio','سبد پروژه‌ها'),
    ('Original Evidence','شواهد اصلی'),
    ('Unresolved','رسیدگی‌نشده'),
    ('Pending Review','در انتظار رسیدگی'),
    ('Narrative / Explanatory Text','شرح رویداد'),
    ('Merged Cell','سلول مرکب'),
    ('Merged Range','محدودهٔ سلول‌های مرکب'),
    ('Merged Status','وضعیت در سلول مرکب'),
    ('Combined Status','وضعیت ترکیبی'),
    ('Mixed Field Content','محتوای ترکیبی فیلد'),
]

UI = {
  'en': {
    'page_title':'General Document | Native Excel review gallery',
    'title':'GENERAL DOCUMENT | NATIVE EXCEL REVIEW GALLERY',
    'subtitle':'{groups} grouped review tasks · {findings} original findings · {projects} projects · actual Excel cell-range screenshots',
    'source_fidelity':'Source fidelity',
    'notice':'Both views are screenshots of actual Excel ranges. The Cleaner view comes from a disposable copy with approved cell-value overrides only. Without an approved correction, the case stays unresolved. No dates, references, or statuses are invented.',
    'all':'All', 'search':'Search document, issue or ID',
    'project':'Project', 'document':'Document', 'revision':'Revision', 'excel_range':'Excel range',
    'reported_cells':'Reported source cells', 'original':'Original Excel view',
    'cleaner':'Cleaner working view (approved overlays only)',
    'not_available':'Excel screenshot not available', 'see_warnings':'See capture warnings',
    'rules':'Rules and recommended corrections', 'findings':'All original findings',
    'finding_id':'Finding ID', 'issue':'Issue type', 'source_cells':'Source cells',
    'original_evidence':'Original evidence', 'requested_fix':'Recommended action / investigation',
    'source_note':'Original finding text, unchanged', 'owner':'Responsible unit',
    'comparison_baseline':'Comparison baseline', 'hash_state':'Source match state',
    'applied':'Approved overlay cells actually applied', 'none':'None', 'unresolved':'Unresolved',
    'warning':'A Cleaner interpretation does not prove the workbook was corrected. Verify any proposed modification against the original correspondence.',
    'technical_original':'Original technical finding (English)', 'language':'Language',
    'language_fa':'فارسی', 'language_en':'English',
    'missing_review':'The workbook or the exact source region is unavailable. Review remains open.',
    'source_state':'Source / working workbook state',
  },
  'fa': {
    'page_title':'دفتر گردش اسناد مهندسی | گالری تصاویر واقعی اکسل',
    'title':'دفتر گردش اسناد مهندسی | گالری رسیدگی به مغایرت‌ها',
    'subtitle':'{groups} گروه رسیدگی · {findings} مغایرت ثبت‌شده · {projects} پروژه · تصاویر واقعی محدوده‌های اکسل',
    'source_fidelity':'اصالت شواهد',
    'notice':'هر دو تصویر از محدودهٔ واقعی اکسل تهیه می‌شوند. نمای نظافتچی فقط اصلاحات تأییدشدهٔ سلولی را در یک نسخهٔ موقت نمایش می‌دهد. بدون اصلاح تأییدشده، مغایرت همچنان رسیدگی‌نشده است. تاریخ، شمارهٔ نامه یا وضعیت حدسی ساخته نمی‌شود.',
    'all':'همه', 'search':'جست‌وجوی سند، مغایرت یا شناسه',
    'project':'پروژه', 'document':'سند', 'revision':'نسخه (Revision)', 'excel_range':'محدودهٔ اکسل',
    'reported_cells':'سلول‌های منبع', 'original':'فایل اکسل اصلی / نمای مبنا',
    'cleaner':'فایل اکسل در حال نظافت (فقط اصلاحات تأییدشده)',
    'not_available':'تصویر واقعی محدودهٔ اکسل موجود نیست', 'see_warnings':'هشدارهای تصویربرداری را بررسی کنید',
    'rules':'قواعد و اقدامات اصلاحی پیشنهادی', 'findings':'تمامی مغایرت‌های اصلی',
    'finding_id':'شناسهٔ مغایرت', 'issue':'نوع مغایرت', 'source_cells':'سلول‌های منبع',
    'original_evidence':'شواهد اصلی', 'requested_fix':'اقدام اصلاحی یا رسیدگی پیشنهادی',
    'source_note':'متن اصلی مغایرت، بدون تغییر', 'owner':'بخش مسئول',
    'comparison_baseline':'مبنای مقایسه', 'hash_state':'وضعیت تطابق فایل',
    'applied':'سلول‌های اصلاح‌شده با مجوز ثبت‌شده', 'none':'هیچ‌کدام', 'unresolved':'رسیدگی‌نشده',
    'warning':'تفسیر نظافتچی به معنی اصلاح فایل اصلی نیست. هر تغییر پیشنهادی باید با نامه یا صورت‌جلسهٔ اصلی راستی‌آزمایی شود.',
    'technical_original':'متن فنی اولیه (انگلیسی)', 'language':'زبان',
    'language_fa':'فارسی', 'language_en':'English',
    'missing_review':'فایل یا محدودهٔ دقیق سند در دسترس نیست؛ رسیدگی همچنان باز است.',
    'source_state':'وضعیت فایل اکسل مبنا و در حال نظافت',
  },
}

# Machine states have bilingual user-facing labels; original machine values remain in CSV.
STATES_FA = {
 'APPROVED_OVERLAY_RENDERED':'اصلاح تأییدشده در نسخهٔ موقت نمایش داده شد',
 'UNRESOLVED':'رسیدگی‌نشده',
 'MISSING_CELL_LOCATION':'آدرس سلول مشخص نیست',
 'MISSING_WORKBOOK':'فایل اکسل در دسترس نیست',
 'CAPTURE_INCOMPLETE':'تصویربرداری ناقص',
 'APPLIED_TO_TEMP_COPY':'در نسخهٔ موقت اعمال شد',
 'ALREADY_EQUAL':'مقدار از پیش برابر است',
 'SKIPPED_PRECONDITION':'شرط اولیهٔ اصلاح برقرار نیست؛ اعمال نشد',
 'SKIPPED_UNSUPPORTED':'عملیات پشتیبانی نمی‌شود',
 'OVERLAY_ERROR':'خطا در اعمال اصلاح',
 'MATCH':'مطابقت تأییدشده',
 'DRIFT_OR_UNKNOWN':'فایل تغییر کرده یا وضعیت نامشخص است',
 'SOURCE_MISSING':'فایل اکسل اصلی در دسترس نیست',
 'NETWORK_MATCHED':'فایل شبکه با نسخهٔ مبنا تطابق دارد',
 'RUN_INPUT_BASELINE':'فایل ورودی همان اجرای نظافتچی',
 'UNAVAILABLE':'در دسترس نیست',
}

# These rules may identify anomalies rather than demonstrated errors. No fix invents evidence.
RULES_FA = {
 'M_LINE': ('مرز ساختاری (M_LINE)','هیچ سلول یا محدودهٔ مرکبی نباید از مرز ساختاری تعیین‌شده عبور کند. جداکننده‌های معتبر باید حفظ شوند؛ بدون تأیید هندسهٔ فایل، ساختار را تغییر ندهید.'),
 'DATE_CHRONOLOGY':('ترتیب زمانی رویدادها','ترتیب سلول‌ها، تعلق به نسخه و ترتیب تاریخی رویدادها را مستقل بررسی کنید. جابه‌جایی در ترتیب سلول‌ها به‌تنهایی دلیل اشتباه تاریخی نیست.'),
 'TEXT_IN_DATE_FIELD_POSITION':('ثبت شرح رویداد در محل تاریخ','بررسی کنید متن شرح رویداد به‌اشتباه در محل تاریخ قرار گرفته است یا خیر. متن اولیه حفظ شود؛ تاریخ فقط از شواهد اصلی تأیید و ثبت گردد.'),
 'POSSIBLE_NARRATIVE_REFERENCE':('ابهام میان شمارهٔ مرجع و شرح رویداد','نوع مقدار را تشخیص دهید: شمارهٔ نامه، ارجاع به جلسه/صورت‌جلسه یا شرح رویداد. متن اصلی را حفظ کنید و صرفاً پس از رسیدگی جای آن را اصلاح کنید.'),
 'RECEIVE_STATUS_ABSENT':('نبود فیلد وضعیت پاسخ','بررسی کنید آیا پاسخ رسمی باید دارای وضعیت باشد یا خیر. نبود وضعیت را خودکار معادل «تأییدنشده» یا N.A قرار ندهید.'),
 'RECEIVE_STATUS_MISSING':('خالی بودن وضعیت پاسخ','وضعیت پاسخ را با نامهٔ اصلی بررسی کنید؛ تنها کد مستند را ثبت کنید و تا زمان تعیین تکلیف، مغایرت را باز نگه دارید.'),
 'MERGED_STATUS':('وضعیت در سلول مرکب','بررسی کنید سلول مرکب عمداً برای یک پاسخ است یا چند رویداد را پوشش می‌دهد. سلول مرکب معتبر لزوماً مغایرت نیست؛ ابهام محتوایی باید رفع شود.'),
 'REVISION_RECEIVE_WITHOUT_SEND':('دریافت بدون ارسال متناظر در همان نسخه','ارتباط پاسخ با ارسال‌های همان نسخه را بررسی کنید. چند ارسال برای یک نسخه مجاز است؛ ارسال فرضی به فایل اضافه نکنید.'),
 'UNRESOLVED_UNDATED_EVENT_ORDER':('ترتیب نامشخص مکاتبات بدون تاریخ','ترتیب تاریخی مکاتبات فاقد تاریخ را از نامه یا صورت‌جلسه بررسی کنید. در نبود شواهد، رویداد را بدون تاریخ و در انتظار رسیدگی نگه دارید.'),
 'UNRESOLVED_UNDATED_EVENT':('رویداد مکاتبه‌ای بدون تاریخ قابل‌استناد','شمارهٔ مرجع و وضعیت فعلی را حفظ کنید. تاریخ را فقط پس از راستی‌آزمایی با سند اصلی وارد کنید.'),
 'MISSING_DATE':('تاریخ ثبت‌نشده','تاریخ دقیق را در سند اصلی پیدا کنید؛ اگر شواهد در دسترس نیست مقدار را رسیدگی‌نشده نگه دارید.'),
 'MISSING_REFERENCE':('شمارهٔ مرجع ثبت‌نشده','شمارهٔ نامه را از مکاتبه بازیابی کنید یا نوع ارجاع به جلسه/شرح رویداد را مشخص نمایید. شناسهٔ ساختگی وارد نکنید.'),
 'MEETING_REFERENCE':('ارجاع به جلسه یا صورت‌جلسه','عبارت جلسه یا صورت‌جلسه می‌تواند مرجع معتبر باشد؛ متن و شواهد اصلی را عیناً حفظ کنید.'),
 'REFERENCE_YEAR_DATE_DISAGREEMENT':('عدم تطابق سال شمارهٔ مرجع و تاریخ','بررسی کنید سال درج‌شده در شمارهٔ نامه به چه معناست و با تاریخ ثبت‌شده چه نسبتی دارد. هیچ مقداری را صرفاً برای همسان‌سازی ظاهری تغییر ندهید.'),
 'POTENTIAL_RECEIVE_BEFORE_SEND':('احتمال تقدم دریافت بر ارسال','دریافت را به ارسال درست مرتبط کنید؛ محل فیزیکی سلول‌ها دلیل کافی برای مغایرت زمانی نیست.'),
 'RECEIVE_BEFORE_MATCHED_SEND':('دریافت زودتر از ارسال متناظر','رابطهٔ ارسال و دریافت و تاریخ هر دو را در شواهد اصلی بررسی کنید. اصلاح تنها با احراز مغایرت واقعی مجاز است.'),
 'UNKNOWN_RECEIVE_STATUS':('وضعیت پاسخ ناشناخته','متن پاسخ را با فهرست وضعیت‌های مصوب مقایسه کنید. شرح رویداد اصلی حفظ شود؛ تبدیل بدون تأیید انجام نشود.'),
 'NO_DATED_EVENTS':('نبود رویداد تاریخ‌دار','بررسی کنید آیا سند دارای مکاتبه بوده است یا خیر. سلول‌های خالی را با تاریخ فرضی پر نکنید.'),
 'TALL_CARD':('کارت مکاتبات با ارتفاع غیرمعمول','ارسال‌ها و دریافت‌های تکرارشونده در یک نسخه را شناسایی کنید؛ همهٔ رویدادهای معتبر به‌صورت مستقل حفظ شوند.'),
 'REPEATED_INTERACTIONS':('مکاتبات متعدد در یک نسخه','تعداد ارسال‌ها می‌تواند بیشتر از دریافت‌ها باشد. هر رویداد را جداگانه و در نسخهٔ صحیح ثبت کنید.'),
 'RECEIVE_STATUS_RELATION':('ارتباط وضعیت پاسخ با دریافت مربوطه','وضعیت باید به دریافت واقعی خود متصل باشد، نه به ارسال مجاور یا نسخهٔ نامرتبط.'),
}

COMPARISON_FA = {
 'no_range':'نشانی معتبر محدودهٔ اکسل وجود ندارد. تصویر ساختگی ایجاد نمی‌شود؛ محل مغایرت باید توسط تیم پروژه تعیین شود.',
 'no_workbook':'فایل اکسل اصلی یا فایل در حال نظافت قابل دسترسی نیست. تصویربرداری و رسیدگی باید تکمیل شود.',
 'unresolved':'هیچ اصلاح سلولیِ تأییدشده‌ای در این محدوده اعمال نشده است. تفسیر نظافتچی یا پذیرش مغایرت، به معنای اصلاح فایل نیست.',
 'applied':'اصلاح سلولی تأییدشده صرفاً در یک نسخهٔ موقت به تصویر درآمده است. ممکن است مغایرت‌های ساختاری یا کسب‌وکاری هنوز رسیدگی‌نشده باشند.',
 'drift':'فایل اصلی ممکن است پس از اجرای نظافتچی تغییر کرده باشد؛ برای مقایسهٔ هم‌نسخه از ورودی همان اجرای نظافتچی استفاده شده، نه الزاماً آخرین فایل شبکه.',
}


def rule_localized(code:str,language:str,english_rules:dict):
    """Translate single and compound issue tags without losing component rules."""
    parts=[x.strip() for x in str(code).split(';') if x.strip()]
    if len(parts)>1:
        translated=[rule_localized(x,language,english_rules) for x in parts]
        return '؛ '.join(x[0] for x in translated) if language=='fa' else '; '.join(x[0] for x in translated), (' '.join(x[1] for x in translated))
    if language=='fa':
        return RULES_FA.get(code,('مغایرت نیازمند طبقه‌بندی','شواهد اصلی را بررسی و اقدام مستند را تعیین کنید؛ در غیر این صورت پرونده در انتظار رسیدگی بماند.'))
    return english_rules.get(code,('Needs classification','Inspect the source and document any supported correction.'))


def state_label(state, language):
    return STATES_FA.get(state,state) if language=='fa' else str(state or '').replace('_',' ')


def comparison_note(group, language):
    if language=='en':return group.get('comparison_note','')
    status=group.get('comparison_status','')
    key={'MISSING_CELL_LOCATION':'no_range','MISSING_WORKBOOK':'no_workbook',
         'APPROVED_OVERLAY_RENDERED':'applied'}.get(status,'unresolved')
    note=COMPARISON_FA[key]
    if group.get('comparison_mode')=='RUN_INPUT_BASELINE':note+=' '+COMPARISON_FA['drift']
    return note


def owner_label(owner,language):
    if language=='fa' and owner=='Engineering + Document Control':return 'بخش مهندسی و کنترل اسناد'
    return owner
