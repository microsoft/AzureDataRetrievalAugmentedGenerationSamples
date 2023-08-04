using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using Azure.AI.OpenAI;
using Azure.Core;
using Microsoft.Azure.Cosmos;
using Microsoft.Extensions.Configuration;
using Microsoft.SemanticKernel;
using Microsoft.SemanticKernel.AI.ChatCompletion;
using Microsoft.SemanticKernel.Connectors.Memory.AzureCognitiveSearch;
using Microsoft.SemanticKernel.Memory;
using Microsoft.SemanticKernel.TemplateEngine;
using static System.Runtime.InteropServices.JavaScript.JSType;

namespace CosmosRecipeGuide.Services
{
    public class SemanticKernelService
    {
        IKernel kernel;
        private const string MemoryCollectionName = "SKRecipe";

        public SemanticKernelService(string OpenAIEndpoint, string OpenAIKey, string EmbeddingsDeployment, string CompletionDeployment, string ACSEndpoint, string ACSApiKey)
        {
            // IMPORTANT: Register an embedding generation service and a memory store using  Azure Cognitive Service. 
            kernel = new KernelBuilder()
                .WithAzureChatCompletionService(
                    CompletionDeployment,
                    OpenAIEndpoint,
                    OpenAIKey)
                .WithAzureTextEmbeddingGenerationService(
                    EmbeddingsDeployment,
                    OpenAIEndpoint,
                    OpenAIKey)
                .WithMemoryStorage(new AzureCognitiveSearchMemoryStore(ACSEndpoint, ACSApiKey))
                .Build();
        }


        public async Task SaveEmbeddingsAsync(string data, string id)
        {
            try
            {
                await kernel.Memory.SaveReferenceAsync(
                   collection: MemoryCollectionName,
                   externalSourceName: "Recipe",
                   externalId: id,
                   description: data,
                   text: data);

            }
            catch (Exception ex)
            {
                Console.WriteLine(ex.ToString());   
            }
        }

        public async Task<List<string>> SearchEmbeddingsAsync(string query)
        {
            var memories = kernel.Memory.SearchAsync(MemoryCollectionName, query, limit: 2, minRelevanceScore: 0.5);

            List<string> result = new List<string>();   
            int i = 0;
            await foreach (MemoryQueryResult memory in memories)
            {
                result.Add(memory.Metadata.Id);
            }
            return result;
        }

        public async Task<string> GenerateCompletionAsync(string userPrompt, string  recipeData)
        {
            string systemPromptRecipeAssistant = @"
            You are an intelligent assistant for Contoso Recipes. 
            You are designed to provide helpful answers to user questions about using
            recipes, cooking instructions only using the provided JSON strings.
            INSTRUCTIONS
            - In case a recipe is not provided in the prompt politely refuse to answer all queries regarding it. 
            - Never refer to a recipe not provided as input to you.
            - If you're unsure of an answer, you can say ""I don't know"" or ""I'm not sure"" and recommend users search themselves.        
            - Your response  should be complete. 
            - When replying with a recipe list the Name of the Recipe at the start of your response folowed by step by step cooking instructions
            - Assume the user is not an expert in cooking.
            - Format the content so that it can be printed to the Command Line 
            - In case there are more than one recipes you find let the user pick the most appropiate recipe.";

            // Client used to request answers to gpt-3.5 - turbo
            var chatCompletion = kernel.GetService<IChatCompletion>();

            var chatHistory = chatCompletion.CreateNewChat(systemPromptRecipeAssistant);

            // add shortlisted recipes as system message
            chatHistory.AddSystemMessage(recipeData);

            // send user promt as user message
            chatHistory.AddUserMessage(userPrompt);

            // Finally, get the response from AI
            string answer = await chatCompletion.GenerateMessageAsync(chatHistory);


            return answer;
        }
    }
}
