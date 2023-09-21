package com.azure.recipe;

import com.azure.recipe.model.Recipe;
import com.azure.recipe.service.CognitiveSearchService;
import com.azure.recipe.service.CosmosDbService;
import com.azure.recipe.service.OpenAIService;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;

import java.io.IOException;
import java.util.*;
import java.util.stream.Collectors;

@Slf4j
public class Main {
    public static CosmosDbService cosmosDbService = null;
    public static OpenAIService openAIEmbeddingService = null;
    public static CognitiveSearchService cogSearchService = null;

    public static void main(String[] args) throws IOException {

        Scanner scanner = new Scanner(System.in);

        cosmosDbService = initCosmosDbService();

        while (true) {
            System.out.println("\n");
            System.out.println("1.\tUpload recipe(s) to Cosmos DB");
            System.out.println("2.\tVectorize the recipe(s) and store it in Cosmos DB");
            System.out.println("3.\tAsk AI Assistant (search for a recipe by name or description, or ask a question)");
            System.out.println("4.\tExit this Application");
            System.out.print("Please select an option: ");
            int selectedOption = Integer.parseInt(scanner.nextLine());
            switch (selectedOption) {
                case 1 -> uploadRecipes();
                case 2 -> generateEmbeddings();
                case 3 -> performSearch(scanner);
                default -> {
                    return;
                }
            }

        }
    }

    private static CosmosDbService initCosmosDbService() {
        CosmosDbService cosmosDbService = new CosmosDbService(AppConfig.cosmosUri,
                AppConfig.cosmosKey,
                AppConfig.cosmosDatabase,
                AppConfig.cosmosContainer
        );
        int recipeWithEmbedding = cosmosDbService.getRecipeCount(true);
        int recipeWithNoEmbedding = cosmosDbService.getRecipeCount(false);

        System.out.println("\n");
        System.out.printf("We have %d vectorized recipe(s) and %d non vectorized recipe(s).",
                recipeWithEmbedding, recipeWithNoEmbedding);

        return cosmosDbService;
    }

    private static OpenAIService initOpenAIService() {
        return new OpenAIService(AppConfig.openAIEndpoint,
                AppConfig.openAIKey,
                AppConfig.openAIEmbeddingDeployment,
                AppConfig.openAICompletionsDeployment,
                AppConfig.openAIMaxToken);
    }

    public static void uploadRecipes() {
        List<Recipe> recipes = Utility.parseDocuments(AppConfig.recipeLocalFolder);

        cosmosDbService.uploadRecipes(recipes);

        int recipeWithEmbedding = cosmosDbService.getRecipeCount(true);
        int recipeWithNoEmbedding = cosmosDbService.getRecipeCount(false);

        System.out.printf("We have %d vectorized recipe(s) and %d non vectorized recipe(s).",
                recipeWithEmbedding, recipeWithNoEmbedding);
    }

    public static void performSearch(Scanner scanner) throws JsonProcessingException {

        if (openAIEmbeddingService == null) {
            log.info("Connecting to Open AI Service..");
            openAIEmbeddingService = initOpenAIService();
        }

        if (cogSearchService == null) {
            log.info("Connecting to Azure Cognitive Search..");
            cogSearchService = new CognitiveSearchService();

            log.info("Checking for Index in Azure Cognitive Search..");
            if (!cogSearchService.checkIndexIfExists()) {
                log.error("Cognitive Search Index not Found, Please Build the index first.");
                return;
            }
        }

        System.out.println("Type the recipe name or your question, hit enter when ready.");
        String userQuery = scanner.nextLine();

        log.info("Converting User Query to Vector..");
        var embeddingVector = openAIEmbeddingService.getEmbeddings(userQuery);

        log.info("Performing Vector Search..");
        List<Float> embeddings = embeddingVector.stream()
                .map(aDouble -> (Float) (float) aDouble.doubleValue())
                .collect(Collectors.toList());

        var ids = cogSearchService.singleVectorSearch(embeddings);

        log.info("Retrieving recipe(s) from Cosmos DB (RAG pattern)..");
        var retrivedDocs = cosmosDbService.getRecipes(ids);

        log.info("Processing {} to generate Chat Response  using OpenAI Service..", retrivedDocs.size());

        StringBuilder retrivedReceipeNames = new StringBuilder();

        for (Recipe recipe : retrivedDocs) {
            recipe.embedding = null; //removing embedding to reduce tokens during chat completion
            retrivedReceipeNames.append(", ").append(recipe.name); //to dispay recipes submitted for Completion
        }

        log.info("Processing '{}' to generate Completion using OpenAI Service..", retrivedReceipeNames);

        String completion =
                openAIEmbeddingService
                        .getChatCompletionAsync(userQuery, Utility.OBJECT_MAPPER.writeValueAsString(retrivedDocs));

        String chatCompletion = completion;

        log.info("AI Assistant Response:", chatCompletion);
        System.out.println(chatCompletion);
    }

    private static void generateEmbeddings() throws JsonProcessingException {
        Map<String, List<Double>> dictEmbeddings = new HashMap<>();
        int recipeWithEmbedding = 0;
        int recipeWithNoEmbedding = 0;
        int recipeCount = 0;

        if (openAIEmbeddingService == null) {
            openAIEmbeddingService = initOpenAIService();
        }


        if (cogSearchService == null) {
            log.info("Connecting to Azure Cognitive Search..");
            cogSearchService = new CognitiveSearchService();

            log.info("Checking for Index in Azure Cognitive Search..");
            if (!cogSearchService.checkIndexIfExists()) {
                log.info("Building Azure Cognitive Search Index..");
                cogSearchService.buildIndex();
            }

        }

        log.info("Getting recipe(s) to vectorize..");
        var recipes = cosmosDbService.getRecipesToVectorize();
        for (Recipe recipe : recipes) {
            recipeCount++;
            log.info("Vectorizing Recipe# {}..", recipeCount);
            var embeddingVector = openAIEmbeddingService.getEmbeddings(Utility.OBJECT_MAPPER.writeValueAsString(recipe));
            recipe.embedding = embeddingVector;
            dictEmbeddings.put(recipe.id, embeddingVector);
        }

        log.info("Updating {} recipe(s) in Cosmos DB for vectors..", recipes.size());
        cosmosDbService.updateRecipesAsync(dictEmbeddings);


        log.info("Indexing {} document(s) on Azure Cognitive Search..", recipes.size());
        cogSearchService.uploadandIndexDocuments(recipes);

        log.info("Getting Updated Recipe Stats");
        recipeWithEmbedding = cosmosDbService.getRecipeCount(true);
        recipeWithNoEmbedding = cosmosDbService.getRecipeCount(false);

        log.info("Vectorized {} recipe(s).", recipeCount);
        System.out.println("\n");
        System.out.printf("We have %d vectorized recipe(s) and %d non vectorized recipe(s).",
                recipeWithEmbedding, recipeWithNoEmbedding);
    }


}