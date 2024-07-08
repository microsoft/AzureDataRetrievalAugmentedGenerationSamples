package com.microsoft.azure.spring.chatgpt.sample.common;

import com.azure.ai.openai.models.ChatCompletions;
import com.azure.ai.openai.models.ChatMessage;
import com.azure.ai.openai.models.ChatRole;
import com.microsoft.azure.spring.chatgpt.sample.common.prompt.PromptTemplate;
import com.microsoft.azure.spring.chatgpt.sample.common.store.CosmosEntity;
import com.microsoft.azure.spring.chatgpt.sample.common.store.VectorStore;

import java.util.ArrayList;
import java.util.List;

public class ChatPlanner {

    private final AzureOpenAIClient client;

    public ChatPlanner(AzureOpenAIClient client, VectorStore store) {
        this.client = client;
        this.store = store;
    }

    private final VectorStore store;

    public ChatCompletions chat(List<ChatMessage> messages) {
        if (messages == null || messages.isEmpty()) {
            throw new IllegalArgumentException("message shouldn't be empty.");
        }

        var lastUserMessage = messages.get(messages.size() - 1);
        if (lastUserMessage.getRole() != ChatRole.USER) {
            throw new IllegalArgumentException("The last message should be in user role.");
        }
        String question = lastUserMessage.getContent();

        // step 1. Convert the user's query text to an embedding
        var response = client.getEmbeddings(List.of(question));
        var embedding = response.getData().get(0).getEmbedding();

        // step 2. Query Top-K nearest text chunks from the vector store
        var candidateDocs = store.searchTopKNearest(embedding, 5, 0.4).stream()
                .map(CosmosEntity::getText).toList();

        // step 3. Populate the prompt template with the chunks
        var prompt = PromptTemplate.formatWithContext(candidateDocs, question);
        var processedMessages = new ArrayList<>(messages);
        processedMessages.set(messages.size() - 1, new ChatMessage(ChatRole.USER).setContent(prompt));

        // step 4. Call to OpenAI chat completion API
        var answer = client.getChatCompletions(processedMessages);
        return answer;
    }
}
