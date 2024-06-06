package com.azure.recipe.service;

import com.azure.ai.openai.OpenAIAsyncClient;
import com.azure.ai.openai.OpenAIClientBuilder;
import com.azure.ai.openai.models.*;
import com.azure.core.credential.AzureKeyCredential;
import com.azure.core.http.policy.ExponentialBackoffOptions;
import com.azure.core.http.policy.RetryOptions;
import lombok.extern.slf4j.Slf4j;

import java.time.Duration;
import java.time.temporal.ChronoUnit;
import java.util.HashMap;
import java.util.List;

@Slf4j
public class OpenAIService {
    private final String openAIEmbeddingDeployment;
    private final String openAICompletionDeployment;
    private final int openAIMaxTokens;

    private final OpenAIAsyncClient openAIClient;
    private final String systemPromptRecipeAssistant = """
            You are an intelligent assistant for Contoso Recipes. 
            You are designed to provide helpful answers to user questions about using
            recipes, cooking instructions only using the provided JSON strings.

            Instructions:
            - In case a recipe is not provided in the prompt politely refuse to answer all queries regarding it. 
            - Never refer to a recipe not provided as input to you.
            - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
            - Your response  should be complete. 
            - List the Name of the Recipe at the start of your response followed by step by step cooking instructions
            - Assume the user is not an expert in cooking.
            - Format the content so that it can be printed to the Command Line 
            - In case there are more than one recipes you find let the user pick the most appropriate recipe. """;


    public OpenAIService(String endpoint,
                         String key,
                         String embeddingsDeployment,
                         String completionDeployment,
                         int maxTokens) {
        this.openAIEmbeddingDeployment = embeddingsDeployment;
        this.openAICompletionDeployment = completionDeployment;
        this.openAIMaxTokens = maxTokens;

        RetryOptions retryOptions = new RetryOptions(
                new ExponentialBackoffOptions()
                        .setMaxRetries(10)
                        .setMaxDelay(Duration.of(2, ChronoUnit.SECONDS))
        );

        if (endpoint.contains("openai.azure.com")) {
            this.openAIClient = new OpenAIClientBuilder()
                    .endpoint(endpoint)
                    .credential(new AzureKeyCredential(key))
                    .retryOptions(retryOptions)
                    .buildAsyncClient();
        } else {
            this.openAIClient = new OpenAIClientBuilder()
                    .endpoint(endpoint)
                    .credential(new NonAzureOpenAIKeyCredential(key))
                    .retryOptions(retryOptions)
                    .buildAsyncClient();
        }
    }

    public List<Double> getEmbeddings(String query) {
        try {
            EmbeddingsOptions options = new EmbeddingsOptions(List.of(query));
            options.setUser("");

            var response = openAIClient.getEmbeddings(openAIEmbeddingDeployment, options).block();

            List<EmbeddingItem> embeddings = response.getData();

            return embeddings.get(0).getEmbedding().stream().toList();
        } catch (Exception ex) {
            log.error("GetEmbeddingsAsync Exception:", ex);
            ex.printStackTrace();
            return null;
        }
    }

    public String getChatCompletionAsync(String userPrompt, String documents) {


        ChatMessage systemMessage = new ChatMessage(ChatRole.SYSTEM);
        systemMessage.setContent(systemPromptRecipeAssistant + documents);
        ChatMessage userMessage = new ChatMessage(ChatRole.USER);
        userMessage.setContent(userPrompt);


        ChatCompletionsOptions options = new ChatCompletionsOptions(List.of(userMessage, systemMessage));
        options.setMaxTokens(openAIMaxTokens);
        options.setTemperature(0.5);
        options.setFrequencyPenalty(0d);
        options.setPresencePenalty(0d);
        options.setN(1);
        options.setLogitBias(new HashMap<>());
        options.setUser("");


        ChatCompletions completions = openAIClient.getChatCompletions(openAICompletionDeployment, options).block();

        return completions.getChoices().get(0).getMessage().getContent();

    }
}
