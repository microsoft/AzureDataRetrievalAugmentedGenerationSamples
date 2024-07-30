package com.microsoft.azure.spring.chatgpt.sample.common;

import com.azure.ai.openai.OpenAIClient;
import com.azure.ai.openai.models.ChatCompletions;
import com.azure.ai.openai.models.ChatCompletionsOptions;
import com.azure.ai.openai.models.ChatMessage;
import com.azure.ai.openai.models.Embeddings;
import com.azure.ai.openai.models.EmbeddingsOptions;

import java.util.List;

public class AzureOpenAIClient {

    private static final String EMBEDDING_MODEL = "text-embedding-ada-002";

    private static final String CHAT_COMPLETION_MODEL = "gpt-35-turbo";

    private static final double TEMPERATURE = 0.7;

    private final OpenAIClient client;

    public AzureOpenAIClient(OpenAIClient client, String embeddingDeploymentId, String chatDeploymentId) {
        this.client = client;
        this.embeddingDeploymentId = embeddingDeploymentId;
        this.chatDeploymentId = chatDeploymentId;
    }

    private final String embeddingDeploymentId;

    private final String chatDeploymentId;

    public Embeddings getEmbeddings(List<String> texts) {
        var response = client.getEmbeddings(embeddingDeploymentId,
                new EmbeddingsOptions(texts).setModel(EMBEDDING_MODEL));
        //log.info("Finished an embedding call with {} tokens.", response.getUsage().getTotalTokens());
        return response;
    }

    public ChatCompletions getChatCompletions(List<ChatMessage> messages) {
        var chatCompletionsOptions = new ChatCompletionsOptions(messages)
                .setModel(CHAT_COMPLETION_MODEL)
                .setTemperature(TEMPERATURE);
        var response = client.getChatCompletions(chatDeploymentId, chatCompletionsOptions);
        //log.info("Finished a chat completion call with {} tokens", response.getUsage().getTotalTokens());
        return response;
    }
}
