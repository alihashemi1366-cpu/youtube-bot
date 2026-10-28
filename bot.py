import os
from datetime import datetime, timezone
import csv
from flask import Flask
import telebot
from telebot import types
from googleapiclient.discovery import build
import google.generativeai as genai

# --- خواندن امن اطلاعات از متغیرهای محیطی هاست ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MY_CHANNEL_HANDLE = os.environ.get("MY_CHANNEL_HANDLE", "UC8J4sFhARqdts04T-DBPz6Q")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
genai.configure(api_key=GEMINI_API_KEY)

# حافظه موقت برای ذخیره کلمه کلیدی هر کاربر
user_keywords = {}

# --- سرور وب برای روشن ماندن روی هاست ابری (Render) ---
app = Flask("")


@app.route("/")
def home():
  return "Robot is alive and running!"


def run_web():
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


# --- توابع کمکی یوتیوب ---
def find_competitor_channels(keyword, max_channels=2):
  try:
    request = youtube.search().list(
        q=keyword, part="snippet", type="channel", maxResults=max_channels
    )
    response = request.execute()
    return [
        {
            "channel_id": item["snippet"]["channelId"],
            "channel_title": item["snippet"]["title"],
        }
        for item in response.get("items", [])
    ]
  except Exception:
    return []


def get_channel_id_by_handle(handle_or_id):
  try:
    print(f"--- در حال جستجوی کانال با مقدار: {handle_or_id} ---")

    if handle_or_id.startswith("UC"):
      request = youtube.channels().list(
          part="id,snippet,statistics", id=handle_or_id
      )
      response = request.execute()
      print(f"پاسخ دریافتی از یوتیوب: {response}")
      if response.get("items"):
        return response["items"][0]

    clean_handle = handle_or_id.lstrip("@")

    try:
      request = youtube.channels().list(
          part="id,snippet,statistics", forHandle=clean_handle
      )
      response = request.execute()
      if response.get("items"):
        return response["items"][0]
    except Exception as err:
      print(f"خطا در روش forHandle: {err}")

    search_request = youtube.search().list(
        q=clean_handle, part="snippet", type="channel", maxResults=1
    )
    search_response = search_request.execute()
    items = search_response.get("items", [])
    if items:
      channel_id = items[0]["snippet"]["channelId"]
      channel_request = youtube.channels().list(
          part="id,snippet,statistics", id=channel_id
      )
      channel_response = channel_request.execute()
      if channel_response.get("items"):
        return channel_response["items"][0]

    print("❌ کانال در هیچ‌کدام از مراحل پیدا نشد.")
    return None
  except Exception as e:
    print(f"🔥 خطای اصلی در دریافت کانال: {e}")
    return None

def get_uploads_playlist_id(channel_id):
  try:
    request = youtube.channels().list(part="contentDetails", id=channel_id)
    response = request.execute()
    return response["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
  except Exception:
    return None


def get_hot_videos_from_playlist(
    playlist_id, channel_title, max_results=10, time_filter="all"
):
  try:
    playlist_request = youtube.playlistItems().list(
        part="snippet", playlistId=playlist_id, maxResults=max_results
    )
    playlist_response = playlist_request.execute()
    video_ids = [
        item["snippet"]["resourceId"]["videoId"]
        for item in playlist_response.get("items", [])
    ]
    if not video_ids:
      return []

    stats_request = youtube.videos().list(
        part="snippet,statistics", id=",".join(video_ids)
    )
    stats_response = stats_request.execute()
    videos_data = []
    now = datetime.now(timezone.utc)

    for video in stats_response.get("items", []):
      published_at_str = video["snippet"]["publishedAt"]
      published_at = datetime.fromisoformat(
          published_at_str.replace("Z", "+00:00")
      )
      hours_elapsed = (now - published_at).total_seconds() / 3600

      if time_filter == "24h" and hours_elapsed > 24:
        continue
      if time_filter == "7d" and hours_elapsed > (7 * 24):
        continue
      if time_filter == "30d" and hours_elapsed > (30 * 24):
        continue

      if hours_elapsed < 1:
        hours_elapsed = 1

      title = video["snippet"]["title"]
      video_id = video["id"]
      view_count = int(video["statistics"].get("viewCount", 0))
      thumbnail_url = video["snippet"]["thumbnails"]["high"]["url"]
      vph = view_count / hours_elapsed

      videos_data.append({
          "channel": channel_title,
          "title": title,
          "url": f"https://youtube.com/watch?v={video_id}",
          "thumbnail": thumbnail_url,
          "views": view_count,
          "vph": round(vph, 2),
      })
    return videos_data
  except Exception:
    return []


def generate_ai_video_ideas(keyword, competitor_titles):
  try:
    model = genai.GenerativeModel("gemini-3.8-flash")
    titles_text = "\n".join(f"- {t}" for t in competitor_titles[:10])
    prompt = (
        f"من یک کانال یوتیوب در حوزه '{keyword}' دارم. عناوین ویدیوهای پربازدید"
        f" اخیر رقبا این است:\n{titles_text}\n\n"
        "به عنوان یک استراتژیست ارشد یوتیوب، لطفاً ۳ ایده و عنوان ویدیوی جدید،"
        " جذاب، کنجکاوی‌برانگیز و بهینه‌شده به زبان فارسی پیشنهاد بده که پتانسیل"
        " وایرال شدن بالایی داشته باشند. برای هر ایده، یک عنوان جذاب و یک"
        " پاراگراف کوتاه درباره نحوه ساخت یا قلاب (Hook) آن بنویس."
    )
    response = model.generate_content(prompt)
    return response.text
  except Exception as e:
    return f"خطا در تولید ایده با هوش مصنوعی: {e}"


def process_my_channel_analysis(chat_id):
  sent_msg = bot.send_message(
      chat_id, f"⏳ در حال دریافت آمار و تحلیل کانال شما ({MY_CHANNEL_HANDLE})..."
  )

  channel_info = get_channel_id_by_handle(MY_CHANNEL_HANDLE)
  if not channel_info:
    bot.edit_message_text(
        "❌ کانال شما پیدا نشد! لطفاً متغیر MY_CHANNEL_HANDLE را بررسی کنید.",
        chat_id=chat_id,
        message_id=sent_msg.message_id,
    )
    return

  channel_title = channel_info["snippet"]["title"]
  channel_id = channel_info["id"]
  stats = channel_info["statistics"]

  playlist_id = get_uploads_playlist_id(channel_id)
  my_videos = []
  if playlist_id:
    my_videos = get_hot_videos_from_playlist(
        playlist_id, channel_title, max_results=5, time_filter="all"
    )

  bot.delete_message(chat_id=chat_id, message_id=sent_msg.message_id)

  summary_text = (
      f"📊 **گزارش کانال شما:** `({channel_title})`\n\n"
      f"👥 سابسکرایب: `{int(stats.get('subscriberCount', 0)):,}`\n"
      f"👁️ کل بازدید: `{int(stats.get('viewCount', 0)):,}`\n\n"
      f"🔥 **۵ ویدیوی اخیر شما:**"
  )
  bot.send_message(chat_id, summary_text, parse_mode="Markdown")

  if my_videos:
    my_videos.sort(key=lambda x: x["vph"], reverse=True)
    for i, vid in enumerate(my_videos, 1):
      markup = types.InlineKeyboardMarkup()
      markup.add(
          types.InlineKeyboardButton("▶️ تماشای ویدیو در یوتیوب", url=vid["url"])
      )
      caption = (
          f"**#{i} | {vid['title']}**\n👁️ بازدید: {vid['views']:,} | ⚡ VPH:"
          f" `{vid['vph']}`"
      )
      bot.send_photo(
          chat_id,
          photo=vid["thumbnail"],
          caption=caption,
          reply_markup=markup,
          parse_mode="Markdown",
      )
  else:
    bot.send_message(chat_id, "ویدیویی در کانال شما یافت نشد.")


def run_competitor_analysis(chat_id, keyword, time_filter):
  competitors = find_competitor_channels(keyword, max_channels=2)
  if not competitors:
    bot.send_message(chat_id, "متأسفانه کانالی با این موضوع پیدا نشد.")
    return

  all_hot_videos = []
  for comp in competitors:
    playlist_id = get_uploads_playlist_id(comp["channel_id"])
    if playlist_id:
      hot_vids = get_hot_videos_from_playlist(
          playlist_id,
          comp["channel_title"],
          max_results=10,
          time_filter=time_filter,
      )
      all_hot_videos.extend(hot_vids)

  all_hot_videos.sort(key=lambda x: x["vph"], reverse=True)
  if not all_hot_videos:
    bot.send_message(
        chat_id,
        "⚠️ در این بازه زمانی ویدیویی برای این حوزه یافت نشد. بازه زمانی دیگری"
        " را امتحان کنید.",
    )
    return

  my_avg_vph = 0
  my_channel_info = get_channel_id_by_handle(MY_CHANNEL_HANDLE)
  if my_channel_info:
    my_playlist_id = get_uploads_playlist_id(my_channel_info["id"])
    if my_playlist_id:
      my_vids = get_hot_videos_from_playlist(
          my_playlist_id, "کانال شما", max_results=5, time_filter="all"
      )
      if my_vids:
        my_avg_vph = sum(v["vph"] for v in my_vids) / len(my_vids)

  competitor_avg_vph = sum(v["vph"] for v in all_hot_videos[:5]) / min(
      5, len(all_hot_videos)
  )

  comparison_report = (
      f"⚖️ **گزارش مقایسه عملکرد (فیلتر: {time_filter}):**\n\n"
      f"⚡ **میانگین VPH رقبا:** `{round(competitor_avg_vph, 2)}`\n"
      f"⚡ **میانگین VPH شما:** `{round(my_avg_vph, 2)}`\n\n"
  )
  if my_avg_vph >= competitor_avg_vph:
    comparison_report += "🏆 سرعت رشد ویدیوهای شما عالی و همپای رقباست! 🚀"
  else:
    comparison_report += (
        "⚠️ رقبا سرعت رشد بالاتری دارند؛ بیایید با کمک هوش مصنوعی ایده جدیدی"
        " پیدا کنیم 👇"
    )

  bot.send_message(chat_id, comparison_report, parse_mode="Markdown")

  sent_ai_msg = bot.send_message(
      chat_id, "🤖 **هوش مصنوعی در حال تحلیل عناوین و ساخت ایده‌ها است...**"
  )
  competitor_titles = [vid["title"] for vid in all_hot_videos]
  ai_suggestions = generate_ai_video_ideas(keyword, competitor_titles)

  bot.edit_message_text(
      f"💡 **پیشنهادهای طلایی هوش مصنوعی:**\n\n{ai_suggestions}",
      chat_id=chat_id,
      message_id=sent_ai_msg.message_id,
      parse_mode="Markdown",
  )

  bot.send_message(chat_id, f"🔥 **۵ ویدیوی داغ برتر رقبا:**", parse_mode="Markdown")

  for i, vid in enumerate(all_hot_videos[:5], 1):
    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("▶️ تماشای ویدیو در یوتیوب", url=vid["url"])
    )
    caption = (
        f"**#{i} | {vid['title']}**\n\n📌 **کانال:**"
        f" {vid['channel']}\n👁️ **بازدید:** {vid['views']:,}\n⚡ **VPH:**"
        f" `{vid['vph']}`"
    )
    bot.send_photo(
        chat_id,
        photo=vid["thumbnail"],
        caption=caption,
        reply_markup=markup,
        parse_mode="Markdown",
    )

  csv_filename = f"competitors_{keyword.replace(' ', '_')}.csv"
  with open(csv_filename, mode="w", encoding="utf-8-sig", newline="") as file:
    writer = csv.writer(file)
    writer.writerow(
        ["نام کانال", "عنوان ویدیو", "لینک ویدیو", "تعداد بازدید", "سرعت رشد (VPH)"]
    )
    for vid in all_hot_videos:
      writer.writerow(
          [vid["channel"], vid["title"], vid["url"], vid["views"], vid["vph"]]
      )

  with open(csv_filename, "rb") as doc_file:
    bot.send_document(
        chat_id, doc_file, caption="📊 فایل کامل تحلیل رقبا (CSV)"
    )

  end_markup = types.InlineKeyboardMarkup()
  btn_restart = types.InlineKeyboardButton(
      "🔄 جستجوی موضوع جدید", callback_data="new_search"
  )
  btn_my_channel_inline = types.InlineKeyboardButton(
      "📊 تحلیل کانال خودم", callback_data="analyze_my_channel"
  )
  end_markup.add(btn_restart, btn_my_channel_inline)

  bot.send_message(
      chat_id, "می‌خواهید کار دیگری انجام دهید؟", reply_markup=end_markup
  )


@bot.message_handler(commands=["start"])
def send_welcome(message):
  markup = types.InlineKeyboardMarkup()
  btn_my_channel = types.InlineKeyboardButton(
      "📊 تحلیل کانال خودم", callback_data="analyze_my_channel"
  )
  markup.add(btn_my_channel)

  bot.reply_to(
      message,
      "سلام! 👋 به ربات استراتژیست و تحلیلگر یوتیوب خوش آمدید.\n\n"
      "🔹 یک **کلمه کلیدی** بفرست تا بازه‌های زمانی مختلف را انتخاب کنی.\n"
      "🔹 یا برای بررسی آمار کانال خودت، روی دکمه زیر کلیک کن:",
      reply_markup=markup,
  )


@bot.message_handler(commands=["mychannel"])
def handle_my_channel(message):
  process_my_channel_analysis(message.chat.id)


@bot.message_handler(func=lambda message: True)
def handle_keyword(message):
  keyword = message.text
  user_keywords[message.chat.id] = keyword

  markup = types.InlineKeyboardMarkup(row_width=2)
  markup.add(
      types.InlineKeyboardButton(
          "⏱️ ۲۴ ساعت گذشته", callback_data="filter_24h"
      ),
      types.InlineKeyboardButton("📅 ۷ روز گذشته", callback_data="filter_7d"),
      types.InlineKeyboardButton("🗓️ ۳۰ روز گذشته", callback_data="filter_30d"),
      types.InlineKeyboardButton("🌐 همه زمان‌ها", callback_data="filter_all"),
  )

  bot.reply_to(
      message,
      f"🔍 کلمه کلیدی **'{keyword}'** دریافت شد.\nلطفاً بازه زمانی مورد نظر"
      " برای فیلتر کردن ویدیوهای رقبا را انتخاب کنید:",
      reply_markup=markup,
      parse_mode="Markdown",
  )


@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
  if call.data == "analyze_my_channel":
    bot.answer_callback_query(call.id, "در حال بارگذاری آمار کانال شما...")
    process_my_channel_analysis(call.message.chat.id)
  elif call.data == "new_search":
    bot.answer_callback_query(call.id)
    bot.send_message(
        call.message.chat.id,
        "✍️ عالی! لطفاً کلمه کلیدی یا موضوع جدید مورد نظرت رو بفرست:",
    )
  elif call.data.startswith("filter_"):
    bot.answer_callback_query(call.id)
    filter_type = call.data.split("_")[1]
    keyword = user_keywords.get(call.message.chat.id, "مستند")

    bot.edit_message_text(
        f"⏳ در حال جستجوی رقبا برای کلمه `{keyword}` (بازه زمانی:"
        f" `{filter_type}`)...",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="Markdown",
    )

    run_competitor_analysis(call.message.chat.id, keyword, filter_type)


if __name__ == "__main__":
  import threading

  t = threading.Thread(target=run_web)
  t.start()
  print("بات مجهز به فیلتر زمانی روشن شد...")
  bot.infinity_polling()
