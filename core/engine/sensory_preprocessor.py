import re
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from textblob import TextBlob

class SensoryPreprocessor:
    """
    Hệ thống 0 (Phản xạ tiền nhận thức): 
    Phân tích thuộc tính vật lý và cảm xúc thô của Input trước khi chuyển cho LLM.
    """
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

    def evaluate_input(self, text: str, user_context: dict = None) -> dict:
        # 1. Phân tích Valence (Vui/Buồn) bằng VADER
        scores = self.analyzer.polarity_scores(text)
        valence = scores['compound']
        
        # 2. Phân tích Arousal (Kích động) dựa trên cường độ văn bản
        # Logic: Dấu chấm than, viết hoa toàn bộ, và các từ nhấn mạnh tăng Arousal
        upper_ratio = len(re.findall(r'[A-Z]', text)) / (len(text) + 1)
        exclamation_count = text.count('!')
        question_count = text.count('?')
        
        arousal = min(1.0, (abs(valence) * 0.5) + (upper_ratio * 0.5) + (exclamation_count * 0.1))
        
        # 3. Phân tích Dominance (Quyền lực/Sự tự tin của User)
        # User ra lệnh (Dominance cao) vs User hỏi han (Dominance thấp)
        blob = TextBlob(text)
        dominance = 0.5
        if re.search(r'\b(do|must|tell|give|search|start|stop)\b', text.lower()):
            dominance += 0.2
        if question_count > 0:
            dominance -= 0.1
            
        # 4. Certainty (Độ chắc chắn)
        certainty = 0.5
        if re.search(r'\b(maybe|perhaps|i think|probably|not sure)\b', text.lower()):
            certainty -= 0.3
        elif re.search(r'\b(sure|defined|always|never|fact)\b', text.lower()):
            certainty += 0.3
            
        # 5. Urgency (Tính cấp bách)
        urgency = 0.0
        if re.search(r'\b(fast|now|immediately|quick|hurry|urgent)\b', text.lower()):
            urgency += 0.6
        urgency = min(1.0, urgency + (exclamation_count * 0.2))

        return {
            "vector": {
                "valence": round(valence, 3),
                "arousal": round(arousal, 3),
                "dominance": round(dominance, 3),
                "certainty": round(certainty, 3),
                "urgency": round(urgency, 3)
            },
            "summary": self._generate_sensory_summary(valence, arousal, urgency)
        }

    def _generate_sensory_summary(self, valence, arousal, urgency) -> str:
        tag = "Bình thường"
        if urgency > 0.7:
             tag = "CẤP BÁCH"
        if arousal > 0.8:
             tag = "KÍCH ĐỘNG"
        if valence < -0.6:
             tag = "TIÊU CỰC NẶNG"
             
        return f"[Hệ thống 0 - Phản xạ tiền nhận thức]: Tín hiệu {tag} ghi nhận. Valence: {valence}, Arousal: {arousal}."
