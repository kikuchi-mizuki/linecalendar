from datetime import datetime, timedelta
from typing import List, Dict

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