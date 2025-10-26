package com.azure.recipe;

import com.typesafe.config.Config;
import com.typesafe.config.ConfigFactory;

public class AppConfig {
    private static final Config config = ConfigFactory.load();
    public static String cosmosUri = config.getString("cosmos.uri");
    public static String cosmosKey = config.getString("cosmos.key");
    public static String cosmosDatabase = config.getString("cosmos.database");
    public static String cosmosContainer = config.getString("cosmos.container");
    public static String recipeLocalFolder = config.getString("dataset.recipe_local_folder");
    public static String openAIEndpoint = config.getString("openai.endpoint");
    public static String openAIKey = config.getString("openai.key");
    public static String openAIEmbeddingDeployment = config.getString("openai.embeddings_deployment");
    public static String openAICompletionsDeployment = config.getString("openai.chat_completions_deployment");
    public static int openAIMaxToken = config.getInt("openai.max_tokens");
}
