package com.azure.recipe;

import com.azure.cosmos.implementation.apachecommons.lang.StringUtils;

public class AppConfig {
    public static String allowedHosts = System.getProperty("ALLOWED_HOSTS",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("ALLOWED_HOSTS")),
                    "*"));
    public static String cosmosUri = System.getProperty("COSMOS_URI",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("COSMOS_URI")),
                    "<COSMOS_URI>"));
    public static String cosmosKey = System.getProperty("COSMOS_KEY",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("COSMOS_KEY")),
                    "<COSMOS_KEY>"));
    public static String cosmosDatabase = System.getProperty("COSMOS_DATABASE",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("COSMOS_DATABASE")),
                    "<COSMOS_DATABASE>"));
    public static String cosmosContainer = System.getProperty("COSMOS_CONTAINER",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("COSMOS_CONTAINER")),
                    "<COSMOS_CONTAINER>"));
    public static String recipeLocalFolder = System.getProperty("RECIPE_LOCAL_FOLDER",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("RECIPE_LOCAL_FOLDER")),
                    "<RECIPE_LOCAL_FOLDER>"));
    public static String openAIEndpoint = System.getProperty("OPENAI_ENDPOINT",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("OPENAI_ENDPOINT")),
                    "<OPENAI_ENDPOINT>"));
    public static String openAIKey = System.getProperty("OPENAI_KEY",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("OPENAI_KEY")),
                    "<OPENAI_KEY>"));
    public static String openAIEmbeddingDeployment = System.getProperty("OPENAI_EMBEDDING_DEPLOYMENT",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("OPENAI_EMBEDDING_DEPLOYMENT")),
                    "<OPENAI_EMBEDDING_DEPLOYMENT>"));
    public static String openAICompletionsDeployment = System.getProperty("OPENAI_COMPLETIONS_DEPLOYMENT",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("OPENAI_COMPLETIONS_DEPLOYMENT")),
                    "<OPENAI_COMPLETIONS_DEPLOYMENT>"));
    public static int openAIMaxToken = Integer.parseInt(System.getProperty("OPENAI_MAX_TOKEN",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("OPENAI_MAX_TOKEN")),
                    "1000")));
    public static String searchServiceEndPoint = System.getProperty("SEARCH_SERVICE_ENDPOINT",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("SEARCH_SERVICE_ENDPOINT")),
                    "<SEARCH_SERVICE_ENDPOINT>"));
    public static String searchIndexName = System.getProperty("SEARCH_INDEX_NAME",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("SEARCH_INDEX_NAME")),
                    "<SEARCH_INDEX_NAME>"));
    public static String searchServiceAdminApiKey = System.getProperty("SEARCH_SERVICE_ADMIN_API_KEY",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("SEARCH_SERVICE_ADMIN_API_KEY")),
                    "<SEARCH_SERVICE_ADMIN_API_KEY>"));
    public static String searchServiceQueryApiKey = System.getProperty("SEARCH_SERVICE_QUERY_API_KEY",
            StringUtils.defaultString(StringUtils.trimToNull(
                            System.getenv().get("SEARCH_SERVICE_QUERY_API_KEY")),
                    "<SEARCH_SERVICE_QUERY_API_KEY>"));
}
