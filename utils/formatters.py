from datetime import datetime, timedelta
from typing import List, Dict
import re

def format_event_list(events: List[Dict], start_time: datetime = None, end_time: datetime = None) -> str:
    def border():
        return '━━━━━━━━━━'
    
    lines = []
    date_list = []
    
    # 日付範囲の設定
    if start_time and end_time:
        current = start_time
        while current <= end_time:
            date_list.append(current)
            current += timedelta(days=1)
    elif start_time:
        date_list.append(start_time)
    else:
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            if start:
                date = datetime.fromisoformat(start.replace('Z', '+00:00')).date()
                if date not in date_list:
                    date_list.append(date)
    
    # 日付順にソート
    date_list.sort()
    
    # 各日付のイベントを表示
    for date in date_list:
        if isinstance(date, datetime):
            date_str = date.strftime('%Y年%m月%d日 (%a)')
            date_key = date.strftime('%Y/%m/%d (%a)')
        else:
            date_str = date.strftime('%Y年%m月%d日 (%a)')
            date_key = date.strftime('%Y/%m/%d (%a)')
        
        lines.append(f'📅 {date_str}')
        lines.append(border())
        
        # その日のイベントを取得
        day_events = []
        for event in events:
            start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
            if start:
                event_date = datetime.fromisoformat(start.replace('Z', '+00:00')).strftime('%Y/%m/%d (%a)')
                if event_date == date_key:
                    day_events.append(event)
        
        if day_events:
            for i, event in enumerate(day_events, 1):
                summary = event.get('summary', '（タイトルなし）')
                start = event.get('start', {}).get('dateTime', event.get('start', {}).get('date'))
                end = event.get('end', {}).get('dateTime', event.get('end', {}).get('date'))
                
                if start and end:
                    if 'T' in start:  # 時刻あり
                        start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                        end_dt = datetime.fromisoformat(end.replace('Z', '+00:00'))
                        time_str = f"{start_dt.strftime('%H:%M')}～{end_dt.strftime('%H:%M')}"
                        lines.append(f"{i}. {summary}")
                        lines.append(f"⏰ {time_str}")
                    else:  # 終日
                        lines.append(f"{i}. {summary}（終日）")
                else:
                    lines.append(f"{i}. {summary}（時間未定）")
                lines.append("")
        else:
            lines.append("予定はありません。")
            lines.append("")
        
        lines.append(border())
    
    return "\n".join(lines)

def format_free_time_calendar(free_slots_by_day: Dict[str, List[Dict]]) -> str:
    """
    カレンダー風に空き時間を整形して返す
    Args:
        free_slots_by_day (Dict[str, List[Dict]]): 日付ごとの空き時間リスト
    Returns:
        str: 整形された空き時間情報
    """
    def border():
        return '━━━━━━━━━━'
    lines = []
    for date_str, slots in free_slots_by_day.items():
        lines.append(f'📅 {date_str}')
        lines.append(border())
        if slots:
            for slot in slots:
                start_time = slot['start'].strftime('%H:%M')
                end_time = slot['end'].strftime('%H:%M')
                lines.append(f"⏰ {start_time}～{end_time}")
        else:
            lines.append("空き時間はありません。")
        lines.append("")
        lines.append(border())
    return "\n".join(lines)

def format_simple_free_time(free_slots_by_day: dict, specified_ranges: List[Dict] = None) -> str:
    """
    シンプルな空き時間表示（例: 6/18（水）\n・8:00〜22:00）
    Args:
        free_slots_by_day (dict): {日付文字列: 空き時間リスト}
        specified_ranges (List[Dict], optional): 指定された時間範囲のリスト
    Returns:
        str: 整形された空き時間情報
    """
    lines = []
    WEEKDAYS = ['月', '火', '水', '木', '金', '土', '日']
    
    # 空き時間がある日のみをフィルタリング
    days_with_slots = {date_str: slots for date_str, slots in free_slots_by_day.items() if slots}
    
    # すべての日に空き時間がない場合
    if not days_with_slots:
        if specified_ranges:
            # 指定された時間範囲がある場合は、その範囲内に空き時間がないことを明示
            lines.append("指定された時間範囲内に空き時間はありません")
            for time_range in specified_ranges:
                date_obj = time_range['date']
                start_time = time_range['start_time']
                end_time = time_range['end_time']
                m = re.match(r'(\d{4})年(\d{2})月(\d{2})日', date_obj.strftime('%Y年%m月%d日'))
                if m:
                    month = int(m.group(2))
                    day = int(m.group(3))
                    youbi = WEEKDAYS[date_obj.weekday()]
                    simple_date = f"{month}/{day}（{youbi}）"
                else:
                    simple_date = date_obj.strftime('%m/%d')
                lines.append(f"・{simple_date} {start_time.strftime('%-H:%M')}〜{end_time.strftime('%-H:%M')}")
        else:
            lines.append("空き時間はありません")
        return "\n".join(lines)
    
    # 空き時間がある日のみを表示
    for date_str, slots in days_with_slots.items():
        # 年を省略し「M/D（曜）」形式に変換（曜日は日本語1文字）
        m = re.match(r'(\d{4})年(\d{2})月(\d{2})日 \((\w{3})\)', date_str)
        if m:
            month = int(m.group(2))
            day = int(m.group(3))
            # 英語曜日→日本語1文字
            en_week = m.group(4)
            en2jp = {'Mon':'月','Tue':'火','Wed':'水','Thu':'木','Fri':'金','Sat':'土','Sun':'日'}
            youbi = en2jp.get(en_week, en_week)
            simple_date = f"{month}/{day}（{youbi}）"
        else:
            simple_date = date_str
        
        # 指定された時間範囲がある場合は、その範囲を表示
        if specified_ranges:
            # この日付に対応する時間範囲を探す
            matching_range = None
            for time_range in specified_ranges:
                if time_range['date'].strftime('%Y年%m月%d日') in date_str:
                    matching_range = time_range
                    break
            
            if matching_range:
                start_time = matching_range['start_time']
                end_time = matching_range['end_time']
                lines.append(f"{simple_date} {start_time.strftime('%-H:%M')}〜{end_time.strftime('%-H:%M')}内の空き時間:")
            else:
                lines.append(simple_date)
        else:
            lines.append(simple_date)
        
        for slot in slots:
            start_time = slot['start'].strftime('%-H:%M') if hasattr(slot['start'], 'strftime') else str(slot['start'])
            end_time = slot['end'].strftime('%-H:%M') if hasattr(slot['end'], 'strftime') else str(slot['end'])
            lines.append(f"・{start_time}〜{end_time}")
        lines.append("")
    return "\n".join(lines).strip() 