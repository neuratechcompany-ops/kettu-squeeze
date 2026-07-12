"""Simple expression parser."""
from enum import Enum
from typing import Union

class TokenType(Enum):
    NUMBER = 1
    PLUS = 2
    MINUS = 3
    MUL = 4
    DIV = 5
    LPAREN = 6
    RPAREN = 7
    EOF = 8

class Token:
    def __init__(self, type_: TokenType, value: str = ""):
        self.type = type_
        self.value = value

class Lexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def next_token(self) -> Token:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1
        if self.pos >= len(self.text):
            return Token(TokenType.EOF)
        ch = self.text[self.pos]
        if ch.isdigit():
            return self._read_number()
        if ch == '+': self.pos += 1; return Token(TokenType.PLUS, '+')
        if ch == '-': self.pos += 1; return Token(TokenType.MINUS, '-')
        if ch == '*': self.pos += 1; return Token(TokenType.MUL, '*')
        if ch == '/': self.pos += 1; return Token(TokenType.DIV, '/')
        if ch == '(': self.pos += 1; return Token(TokenType.LPAREN, '(')
        if ch == ')': self.pos += 1; return Token(TokenType.RPAREN, ')')
        raise ValueError(f"Unknown character: {ch}")

    def _read_number(self) -> Token:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos].isdigit():
            self.pos += 1
        return Token(TokenType.NUMBER, self.text[start:self.pos])

class Parser:
    def __init__(self, lexer: Lexer):
        self.lexer = lexer
        self.current = lexer.next_token()

    def parse(self) -> int:
        result = self._expr()
        if self.current.type != TokenType.EOF:
            raise ValueError("Unexpected token")
        return result

    def _expr(self) -> int:
        result = self._term()
        while self.current.type in (TokenType.PLUS, TokenType.MINUS):
            if self.current.type == TokenType.PLUS:
                self._eat(TokenType.PLUS)
                result += self._term()
            else:
                self._eat(TokenType.MINUS)
                result -= self._term()
        return result

    def _term(self) -> int:
        result = self._factor()
        while self.current.type in (TokenType.MUL, TokenType.DIV):
            if self.current.type == TokenType.MUL:
                self._eat(TokenType.MUL)
                result *= self._factor()
            else:
                self._eat(TokenType.DIV)
                result //= self._factor()
        return result

    def _factor(self) -> int:
        if self.current.type == TokenType.NUMBER:
            val = int(self.current.value)
            self._eat(TokenType.NUMBER)
            return val
        if self.current.type == TokenType.LPAREN:
            self._eat(TokenType.LPAREN)
            result = self._expr()
            self._eat(TokenType.RPAREN)
            return result
        raise ValueError("Expected number or '('")

    def _eat(self, type_: TokenType):
        if self.current.type == type_:
            self.current = self.lexer.next_token()
        else:
            raise ValueError(f"Expected {type_}, got {self.current.type}")
