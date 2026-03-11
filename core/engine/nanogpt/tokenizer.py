import collections
import json
import re

class BPETokenizer:
    """Production-grade BPE Tokenizer with efficient tuple-based training"""
    def __init__(self, vocab_size=8192):
        self.vocab_size = vocab_size
        self.merges = {}
        self.vocab = {}
        self.inv_vocab = {}

    def train(self, text):
        if not text: return
        
        # 1. Thu thập toàn bộ ký tự đơn duy nhất trong văn bản
        unique_chars = sorted(list(set(text)))
        self.vocab = {"<UNK>": 0}
        for c in unique_chars:
            if c not in self.vocab:
                self.vocab[c] = len(self.vocab)
        self.inv_vocab = {v: k for k, v in self.vocab.items()}
        
        base_vocab_size = len(self.vocab)
        
        # 2. Phân tách văn bản tĩnh
        # Giữ lại toàn bộ dấu cách, xuống dòng thông qua chia words bằng \S+|\s+
        words = collections.defaultdict(int)
        for w in re.findall(r'\S+|\s+', text):
            # Lưu mảng tuple thay vì str để tránh lỗi gộp dấu cách
            words[tuple(w)] += 1
            
        num_merges = max(0, self.vocab_size - base_vocab_size)
        
        for i in range(num_merges):
            pairs = collections.defaultdict(int)
            for word, freq in words.items():
                for j in range(len(word)-1):
                    pairs[word[j], word[j+1]] += freq
            
            if not pairs: break
            best = max(pairs, key=pairs.get)
            
            merge_idx = base_vocab_size + i
            self.merges[best] = merge_idx
            
            new_token = "".join(best)
            self.vocab[new_token] = merge_idx
            self.inv_vocab[merge_idx] = new_token
            
            # Update word freq
            new_words = collections.defaultdict(int)
            for word, freq in words.items():
                if len(word) < 2:
                    new_words[word] += freq
                    continue
                
                new_word = []
                j = 0
                while j < len(word):
                    if j < len(word)-1 and (word[j], word[j+1]) == best:
                        new_word.append(new_token)
                        j += 2
                    else:
                        new_word.append(word[j])
                        j += 1
                new_words[tuple(new_word)] += freq
            words = new_words

    def encode(self, text):
        if not text: return []
        tokens = []
        for w in re.findall(r'\S+|\s+', text):
            word = list(w)
            while len(word) > 1:
                pairs = [(word[i], word[i+1]) for i in range(len(word)-1)]
                found_pair = None
                min_rank = float('inf')
                for p in pairs:
                    rank = self.merges.get(p, float('inf'))
                    if rank < min_rank:
                        min_rank = rank
                        found_pair = p
                
                if found_pair is None: break
                
                new_word = []
                j = 0
                while j < len(word):
                    if j < len(word)-1 and (word[j], word[j+1]) == found_pair:
                        new_word.append("".join(found_pair))
                        j += 2
                    else:
                        new_word.append(word[j])
                        j += 1
                word = new_word
            
            for t in word:
                tokens.append(self.vocab.get(t, self.vocab.get("<UNK>", 0)))
                
        return tokens

    def decode(self, tokens):
        return "".join([self.inv_vocab.get(t, "") for t in tokens])

    def save(self, filepath):
        # Lưu các merge keys dạng tuple -> list
        merges_list = [[k[0], k[1], v] for k, v in self.merges.items()]
        data = {
            "vocab_size": len(self.vocab),
            "vocab": self.vocab,
            "inv_vocab": {str(k): v for k, v in self.inv_vocab.items()},
            "merges": merges_list
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.vocab_size = data["vocab_size"]
        self.vocab = data["vocab"]
        self.inv_vocab = {int(k): v for k, v in data["inv_vocab"].items()}
        self.merges = {tuple((item[0], item[1])): item[2] for item in data["merges"]}

