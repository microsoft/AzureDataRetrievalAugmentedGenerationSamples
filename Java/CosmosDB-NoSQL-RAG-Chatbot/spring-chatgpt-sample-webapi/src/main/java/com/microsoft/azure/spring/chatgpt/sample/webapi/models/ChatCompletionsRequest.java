package com.microsoft.azure.spring.chatgpt.sample.webapi.models;

import com.azure.ai.openai.models.ChatMessage;

import java.util.List;

public class ChatCompletionsRequest {
    private List<ChatMessage> messages;

    public List<ChatMessage> getMessages() {
        return messages;
    }
}
