import collections
import json
import re

class BPETokenizer:
    """Production-grade BPE Tokenizer with efficient training"""
    def __init__(self, vocab_size=1000):
        self.vocab_size = vocab_size
        self.merges = {}
        self.vocab = {chr(i): i for i in range(256)}
        self.inv_vocab = {i: chr(i) for i in range(256)}

    def train(self, text):
        if not text: return
        
        # Pre-tokenize text into words using regex to avoid O(N^2) on the entire 6MB string
        word_freqs = collections.defaultdict(int)
        # Match words (including vietnamese characters) and punctuation safely
        for w in re.findall(r'\w+|[^\w\s]', text):
            # Format: 'h e l l o' + ' </w>'
            chars = " ".join(list(w)) + " </w>"
            word_freqs[chars] += 1
            
        words = word_freqs
        
        num_merges = self.vocab_size - 256
        for i in range(num_merges):
            pairs = collections.defaultdict(int)
            for word, freq in words.items():
                symbols = word.split()
                for j in range(len(symbols)-1):
                    pairs[symbols[j], symbols[j+1]] += freq
            
            if not pairs: break
            best = max(pairs, key=pairs.get)
            merge_idx = i + 256
            self.merges[best] = merge_idx
            self.vocab["".join(best)] = merge_idx
            self.inv_vocab[merge_idx] = "".join(best)
            
            # Update vocab training
            new_words = {}
            pair_str = " ".join(best)
            replacement = "".join(best)
            for word, freq in words.items():
                new_word = word.replace(pair_str, replacement)
                new_words[new_word] = freq
            words = new_words

    def encode(self, text):
        if not text: return []
        
        # We need to pre-tokenize encode exactly like train
        tokens = []
        for w in re.findall(r'\w+|[^\w\s]', text):
            word = list(w) + ["</w>"]
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
            tokens.extend([self.vocab.get(t, ord(t[0]) if len(t)==1 else 0) for t in word])
            
        return tokens

    def decode(self, tokens):
        res = "".join([self.inv_vocab.get(t, chr(t) if t < 256 else "") for t in tokens])
        return res.replace("</w>", "")

    def save(self, filepath):
        # Convert tuple keys to strings for JSON
        merges_str = {f"{k[0]} {k[1]}": v for k, v in self.merges.items()}
        data = {
            "vocab_size": self.vocab_size,
            "vocab": self.vocab,
            "inv_vocab": {str(k): v for k, v in self.inv_vocab.items()},
            "merges": merges_str
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)

    def load(self, filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.vocab_size = data["vocab_size"]
        self.vocab = data["vocab"]
        self.inv_vocab = {int(k): v for k, v in data["inv_vocab"].items()}
        # Reconstruct tuple keys from strings
        self.merges = {tuple(k.split()): v for k, v in data["merges"].items()}

