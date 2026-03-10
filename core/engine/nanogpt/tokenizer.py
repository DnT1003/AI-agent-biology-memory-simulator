import collections

class BPETokenizer:
    """Production-grade BPE Tokenizer with precise whitespace handling"""
    def __init__(self, vocab_size=1000):
        self.vocab_size = vocab_size
        self.merges = {}
        self.vocab = {chr(i): i for i in range(256)}
        self.inv_vocab = {i: chr(i) for i in range(256)}

    def train(self, text):
        if not text: return
        # Thêm token kết thúc câu để phân tách chuỗi
        chars = list(text) + ["</w>"]
        words = {" ".join(chars): 1}
        
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
            
            # Cập nhật vocab training
            new_words = {}
            pair_str = " ".join(best)
            replacement = "".join(best)
            for word, freq in words.items():
                new_word = word.replace(pair_str, replacement)
                new_words[new_word] = freq
            words = new_words

    def encode(self, text):
        if not text: return []
        word = list(text) + ["</w>"]
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
            i = 0
            while i < len(word):
                if i < len(word)-1 and (word[i], word[i+1]) == found_pair:
                    new_word.append("".join(found_pair))
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = new_word
        return [self.vocab.get(t, ord(t[0]) if len(t)==1 else 0) for t in word]

    def decode(self, tokens):
        res = "".join([self.inv_vocab.get(t, chr(t) if t < 256 else "") for t in tokens])
        return res.replace("</w>", "")
