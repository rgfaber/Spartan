# mlx_thinking_processor.py
import mlx.core as mx

class MLXThinkingTokenBudgetProcessor:
    """
    A custom LogitsProcessor that forces the model to stop thinking and start
    the JSON block, and then deactivates itself to allow generation to continue.
    """
    def __init__(self, max_thinking_tokens: int, tokenizer):
        self.max_thinking_tokens = max_thinking_tokens
        self.tokenizer = tokenizer
        self.tokens_generated = 0
        self.enforce_step = 0  # 0=inactive, 1-4=forcing sequence

        try:
            self.sequence_to_force = [
                self.tokenizer.encode("\n")[0],
                self.tokenizer.encode("</think>")[0],
                self.tokenizer.encode("\n")[0],
                self.tokenizer.encode("[")[0]
            ]
        except Exception as e:
            raise ValueError(f"Tokenizer failed to encode critical transition tokens: {e}")

    def __call__(self, input_ids: mx.array, scores: mx.array) -> mx.array:
        # If the processor is already done, do nothing.
        if self.enforce_step == -1:
            return scores

        # If we are not in the enforcement phase, just count tokens.
        if self.enforce_step == 0:
            self.tokens_generated += 1
            if self.tokens_generated >= self.max_thinking_tokens:
                self.enforce_step = 1 # Begin enforcement on the next token.

        # If we are in the enforcement phase...
        if self.enforce_step > 0:
            token_to_force = self.sequence_to_force[self.enforce_step - 1]
            
            scores[:, :] = -float("inf")
            scores[:, token_to_force] = 0.0
            
            # If we just forced the last token in the sequence...
            if self.enforce_step == len(self.sequence_to_force):
                # --- THIS IS THE FIX ---
                # Deactivate the processor permanently for this generation.
                self.enforce_step = -1
            else:
                # Otherwise, move to the next step.
                self.enforce_step += 1
        
        return scores