import collections
import json
import re
import unicodedata

class BPETokenizer:
    """Production-grade BBPE Tokenizer (Byte-Level) optimized for Vietnamese"""
    def __init__(self, vocab_size=16384): 
        self.vocab_size = vocab_size
        self.merges = {}
        self.vocab = {}
        self.inv_vocab = {}
        self.cache = {} 

    def _normalize(self, text):
        return unicodedata.normalize('NFC', text)

    def train(self, text):
        text = self._normalize(text)
        
        # Khởi tạo base vocab bằng bytes (0-255)
        self.vocab = {bytes([i]): i for i in range(256)}
        self.inv_vocab = {i: bytes([i]) for i in range(256)}
        
        # Giai đoạn 1: Đếm tần suất các từ (Sử dụng Regex tốt hơn để tránh byte mồ côi)
        # Regex này giữ nguyên các cụm từ/ký tự có nghĩa
        pat = re.compile(r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?[^\s\w\d_]+|\s+(?!\S)|\s+""")
        
        words = collections.Counter()
        for w in pat.findall(text):
            word_bytes = tuple(bytes([b]) for b in w.encode('utf-8'))
            words[word_bytes] += 1

        num_merges = self.vocab_size - 256
        print(f"[Tokenizer] Training on {len(text)} chars, initial unique words: {len(words)}")
        
        for i in range(num_merges):
            # Giai đoạn 2: Tìm cặp byte xuất hiện nhiều nhất
            pairs = collections.Counter()
            for word, freq in words.items():
                for j in range(len(word)-1):
                    pairs[word[j], word[j+1]] += freq
            
            if not pairs: break
            best = pairs.most_common(1)[0][0]
            
            merge_idx = 256 + i
            self.merges[best] = merge_idx
            new_token = best[0] + best[1] 
            self.vocab[new_token] = merge_idx
            self.inv_vocab[merge_idx] = new_token

            # Giai đoạn 3: Cập nhật danh sách từ (Gộp cặp 'best' lại)
            new_words = collections.Counter()
            for word, freq in words.items():
                new_word = []
                j = 0
                while j < len(word):
                    if j < len(word)-1 and (word[j], word[j+1]) == best:
                        new_word.append(new_token)
                        j += 2
                    else:
                        new_word.append(word[j])
                        j += 1
                new_words[tuple(new_word)] = freq
            words = new_words
            
            if (i+1) % 500 == 0 or i == num_merges - 1:
                print(f"[Tokenizer]: Merged {i+1}/{num_merges} BBPE tokens...")

    def encode(self, text):
        text = self._normalize(text)
        if not text: return []
        
        final_tokens = []
        for w in re.findall(r'\S+|\s+', text):
            word_bytes = tuple(bytes([b]) for b in w.encode('utf-8'))
            tokens = self._bpe(word_bytes)
            final_tokens.extend([self.vocab.get(t, 0) for t in tokens])
        return final_tokens

    def _bpe(self, word):
        if word in self.cache: return self.cache[word]
        
        new_word = list(word)
        while len(new_word) > 1:
            pairs = [(new_word[i], new_word[i+1]) for i in range(len(new_word)-1)]
            pair = min(pairs, key=lambda p: self.merges.get(p, float('inf')))
            
            if pair not in self.merges: break
            
            next_word = []
            i = 0
            while i < len(new_word):
                if i < len(new_word)-1 and (new_word[i], new_word[i+1]) == pair:
                    next_word.append(pair[0] + pair[1])
                    i += 2
                else:
                    next_word.append(new_word[i])
                    i += 1
            new_word = next_word
            
        self.cache[word] = tuple(new_word)
        return new_word

    def decode(self, tokens):
        byte_data = b"".join([self.inv_vocab.get(t, b"") for t in tokens])
        return byte_data.decode('utf-8', errors='replace').replace('\x00', '')

    def save(self, filepath):
        # Chuyển bytes thành chuỗi Hex để lưu JSON an toàn
        merges_list = [[k[0].hex(), k[1].hex(), v] for k, v in self.merges.items()]
        vocab_hex = {k.hex(): v for k, v in self.vocab.items()}
        inv_vocab_hex = {str(k): v.hex() for k, v in self.inv_vocab.items()}
        
        data = {
            "vocab_size": self.vocab_size,
            "vocab": vocab_hex,
            "inv_vocab": inv_vocab_hex,
            "merges": merges_list
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=True, indent=2)

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        self.vocab_size = data.get("vocab_size", len(data["vocab"]))
        self.vocab = {bytes.fromhex(k): v for k, v in data["vocab"].items()}
        self.inv_vocab = {int(k): bytes.fromhex(v) for k, v in data["inv_vocab"].items()}
        self.merges = {tuple((bytes.fromhex(item[0]), bytes.fromhex(item[1]))): item[2] for item in data["merges"]}
